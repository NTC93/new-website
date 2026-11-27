<?php
declare(strict_types=1);
// No configuration or secrets in Git; the local config is provisioned separately.
ini_set('display_errors','0');
header('X-Content-Type-Options: nosniff');
header('X-Robots-Tag: noindex, nofollow');
header('Referrer-Policy: same-origin');
header('Cache-Control: no-store');
header('Permissions-Policy: camera=(), microphone=(), geolocation=()');
header("Content-Security-Policy: default-src 'self'; style-src 'self'; img-src 'self' https:; form-action 'self'; frame-ancestors 'none'; base-uri 'none'");
date_default_timezone_set('Europe/Berlin');
$configFile=__DIR__.'/private/config.php';
function e($s): string {return htmlspecialchars((string)$s, ENT_QUOTES|ENT_SUBSTITUTE,'UTF-8');}
function stop(int $status,string $msg): never {http_response_code($status);echo e($msg);exit;}
if (!is_file($configFile)) {stop(503,'NTC Redaktionssystem – Datenbank noch nicht eingerichtet.');}
$c=require $configFile;
if (!is_array($c)||empty($c['dsn'])||empty($c['db_user']))stop(503,'Konfiguration fehlt.');
try {
 $db=new PDO($c['dsn'],$c['db_user'],$c['db_password']??'',[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC,PDO::ATTR_EMULATE_PREPARES=>false]);
 $db->exec("SET time_zone = ".$db->quote(date('P')));
 $db->exec("CREATE TABLE IF NOT EXISTS cms_users (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, login VARCHAR(100) NOT NULL UNIQUE, name VARCHAR(150) NOT NULL, password_hash VARCHAR(255) NOT NULL, role ENUM('admin','editor','author') NOT NULL, active TINYINT NOT NULL DEFAULT 1, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
 $db->exec("CREATE TABLE IF NOT EXISTS cms_entries (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, kind VARCHAR(32) NOT NULL, slug VARCHAR(180) NOT NULL, title VARCHAR(240) NOT NULL, data LONGTEXT NOT NULL, state ENUM('draft','published','archived') NOT NULL DEFAULT 'draft', published_data LONGTEXT NULL, published_title VARCHAR(240) NULL, publish_at DATETIME NULL, position INT NOT NULL DEFAULT 0, owner_id BIGINT UNSIGNED NOT NULL, updated_by BIGINT UNSIGNED NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP, UNIQUE KEY kind_slug(kind,slug), KEY public_entries(kind,state,publish_at)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
 $db->exec("CREATE TABLE IF NOT EXISTS cms_revisions (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, entry_id BIGINT UNSIGNED NOT NULL, actor_id BIGINT UNSIGNED NOT NULL, snapshot LONGTEXT NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, KEY entry_history(entry_id,id)) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
 $db->exec("CREATE TABLE IF NOT EXISTS cms_media (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, name VARCHAR(240) NOT NULL, mime VARCHAR(80) NOT NULL, bytes MEDIUMBLOB NOT NULL, alt VARCHAR(240) NOT NULL, owner_id BIGINT UNSIGNED NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
 $db->exec("CREATE TABLE IF NOT EXISTS cms_log (id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, actor_id BIGINT UNSIGNED NOT NULL, action VARCHAR(80) NOT NULL, detail VARCHAR(240) NOT NULL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
 $db->exec("CREATE TABLE IF NOT EXISTS cms_attempts (fingerprint CHAR(64) PRIMARY KEY, tries INT NOT NULL, window_start INT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
} catch(Throwable $ex){error_log('NTC CMS database unavailable');stop(503,'Datenbankverbindung nicht verfügbar.');}
function run(string $sql,array $p=[]): PDOStatement {global $db;$q=$db->prepare($sql);$q->execute($p);return $q;}
function jsonout($v): never {header('Content-Type: application/json; charset=utf-8');echo json_encode($v,JSON_UNESCAPED_UNICODE|JSON_INVALID_UTF8_SUBSTITUTE);exit;}
$types=[
 'pages'=>['Unterseiten',['path'=>'URL-Pfad','intro'=>'Einleitung','body'=>'Inhalt (Text, Absätze)','image'=>'Bild-URL','seo'=>'Meta-Beschreibung']],
 'news'=>['Nachrichten',['teaser'=>'Kurztext','body'=>'Artikeltext','image'=>'Bild-URL','category'=>'Kategorie']],
 'events'=>['Termine',['date'=>'Beginn (JJJJ-MM-TT)','end_date'=>'Enddatum inkl. (JJJJ-MM-TT, optional)','time'=>'Beginn (HH:MM)','end_time'=>'Endzeit (HH:MM, optional)','venue'=>'Ort','body'=>'Beschreibung','link'=>'Weiterführender Link','status'=>'Terminstatus (Bestätigt / Voraussichtlich)']],
 'sponsors'=>['Sponsoren',['image'=>'Logo-URL','link'=>'Website','body'=>'Beschreibung','category'=>'Sponsorenkategorie']],
 'slides'=>['Startseiten-Slider',['image'=>'Bild-URL','body'=>'Untertitel','link'=>'Ziel-URL','button'=>'Buttontext']],
 'teams'=>['Mannschaften',['category'=>'Altersklasse','body'=>'Beschreibung','image'=>'Mannschaftsfoto','link'=>'nuLiga-Link']],
 'people'=>['Vorstand & Trainer',['category'=>'Bereich','role'=>'Funktion','body'=>'Profil','image'=>'Porträt','email'=>'E-Mail']],
 'documents'=>['Dokumente',['category'=>'Bereich','link'=>'Dokument-URL','body'=>'Beschreibung']],
 'notices'=>['Hinweise',['body'=>'Hinweistext','link'=>'Weitere Informationen']],
 'menus'=>['Navigation',['category'=>'Hauptbereich','link'=>'Ziel-URL']],
 'settings'=>['Website-Einstellungen',['body'=>'Wert','link'=>'URL']]
];
$long=['intro','body','teaser','seo'];

/* One-time seed of the previously published club events. INSERT IGNORE preserves
   subsequent editorial edits, archived entries and existing slugs. */
$eventSeed=json_decode('[{"slug":"ntc-geburtstagsbrunch-2026","title":"NTC-Geburtstagsbrunch","data":{"date":"2026-12-06","time":"11:00–15:00","venue":"Clubhaus NTC 93","body":"Brunchbuffet für 20 € pro Person inklusive Sektempfang. Verbindliche Anmeldung mit Personenzahl an info@ntc93.de erforderlich.","link":"/33-jahre-ntc-und-ein-brunch-zum-anstossen/","status":"Bestätigt"}},{"slug":"arbeitseinsatz-tennishalle-2026-12","title":"Arbeitseinsatz Tennishalle","data":{"date":"2026-12-19","time":"","venue":"Tennishalle NTC 93","body":"Voraussichtlicher Termin. Die Uhrzeit und endgültige Bestätigung stehen noch aus.","link":"/fit-fuer-den-winter-unsere-halle-ist-bereit/","status":"Voraussichtlich"}},{"slug":"regelworkshop-2027","title":"Tennis-Regelworkshop","data":{"date":"2027-03-04","end_date":"","time":"19:00","end_time":"","venue":"Clubhaus NTC 93","body":"Regelwissen und Praxis, Dauer ca. 2–2,5 Stunden. NTC-Mitglieder und berechtigte Angehörige kostenlos; Gäste bis 31.01.2027 15 €, danach 25 €.","link":"https://tennis-schiri.de/turniere/","status":"Bestätigt"}},{"slug":"indoor-mixed-2027","title":"Indoor-Mixed-LK-Turnier","data":{"date":"2027-03-27","end_date":"","time":"","end_time":"","venue":"Tennishalle NTC 93","body":"Mixed 40 Doppel und Mixed Aktive Doppel, LK 1,0–25,0. Meldeschluss 25.03.2027, 18 Uhr; Auslosung 19 Uhr.","link":"https://tennis-schiri.de/turniere/","status":"Bestätigt"}},{"slug":"lk-neuenhagen-2027-04-24","title":"LK-Turnier Neuenhagen","data":{"date":"2027-04-24","end_date":"","time":"","end_time":"","venue":"NTC 93, Hildesheimer Straße 11–13, Neuenhagen","body":"Outdoor, Sand. Ausschreibung und Konkurrenzen folgen.","link":"https://tennis-schiri.de/turniere/","status":"Bestätigt"}},{"slug":"lk-neuenhagen-2027-04-25","title":"LK-Turnier Neuenhagen","data":{"date":"2027-04-25","end_date":"","time":"","end_time":"","venue":"NTC 93, Hildesheimer Straße 11–13, Neuenhagen","body":"Outdoor, Sand. Ausschreibung und Konkurrenzen folgen.","link":"https://tennis-schiri.de/turniere/","status":"Bestätigt"}},{"slug":"neuenhagen-open-2027","title":"22. Neuenhagen Open (A4)","data":{"date":"2027-06-15","end_date":"2027-06-20","time":"","end_time":"","venue":"NTC 93, Hildesheimer Straße 11–13, Neuenhagen","body":"DTB-Ranglistenturnier A4 auf Sand. Ausschreibung und Anmeldung folgen.","link":"https://tennis-schiri.de/turniere/termin.html?id=turnier-neuenhagen-open-2027","status":"Bestätigt"}},{"slug":"neuenhagen-senior-open-2027","title":"10. Neuenhagen Senior Open (S3)","data":{"date":"2027-06-18","end_date":"2027-06-23","time":"","end_time":"","venue":"NTC 93, Hildesheimer Straße 11–13, Neuenhagen","body":"DTB-Ranglistenturnier S3 auf Sand. Ausschreibung und Anmeldung folgen.","link":"https://tennis-schiri.de/turniere/","status":"Bestätigt"}}]',true);
$firstAdmin=(int)run("SELECT COALESCE(MIN(id),0) FROM cms_users WHERE role='admin'")->fetchColumn();
if($firstAdmin){
 foreach($eventSeed as $event){
  $payload=json_encode($event['data'],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);
  run("INSERT IGNORE INTO cms_entries(kind,slug,title,data,state,published_data,published_title,publish_at,position,owner_id,updated_by) VALUES('events',?,?,?,'published',?,?,NOW(),0,?,?)",[$event['slug'],$event['title'],$payload,$payload,$event['title'],$firstAdmin,$firstAdmin]);
 }
}

$mediaId=(int)($_GET['media']??0);
if ($mediaId>0) {
 // Media is an explicitly public library; no private documents or member records.
 $m=run('SELECT mime,bytes FROM cms_media WHERE id=?',[$mediaId])->fetch();
 if(!$m)stop(404,'Datei nicht gefunden.');
 header('Content-Type: '.$m['mime']);if($m['mime']==='application/pdf')header('Content-Disposition: attachment; filename="NTC-Dokument.pdf"');header('Cache-Control: public, max-age=86400');echo $m['bytes'];exit;
}

/* Subscribable RFC 5545 feed, using only publicly published events.
   Event slugs are immutable after publication and form stable calendar UIDs. */
if(isset($_GET['calendar'])){
 $rows=[];
 if(!$firstAdmin){$rows=$eventSeed;}
 else{
  foreach(run("SELECT slug,published_title AS title,published_data AS data,updated_at FROM cms_entries WHERE kind='events' AND state!='archived' AND published_data IS NOT NULL AND publish_at<=NOW()") as $row){
   $row['data']=json_decode($row['data'],true)??[];$rows[]=$row;
  }
 }
 function ics_escape(string $v):string{return str_replace(["\\","\r\n","\r","\n",",",";"],["\\\\","\\n","\\n","\\n","\\,","\\;"],$v);}
 function ics_line(string $v):string{
  $parts=preg_split('//u',$v,-1,PREG_SPLIT_NO_EMPTY);if($parts===false)return '';
  $out='';$line='';
  foreach($parts as $c){if(strlen($line)+strlen($c)>75){$out.=$line."\r\n";$line=' ';}$line.=$c;}
  return $out.$line."\r\n";
 }
 function ics_date($value):?DateTimeImmutable{
  if(!is_string($value)||!preg_match('/^\d{4}-\d{2}-\d{2}$/D',$value))return null;
  $date=DateTimeImmutable::createFromFormat('!Y-m-d',$value,new DateTimeZone('Europe/Berlin'));
  return $date&&$date->format('Y-m-d')===$value?$date:null;
 }
 $lines=['BEGIN:VCALENDAR','VERSION:2.0','PRODID:-//NTC 93//Vereinstermine//DE','CALSCALE:GREGORIAN','METHOD:PUBLISH','X-WR-CALNAME:NTC 93 - Vereinstermine','X-WR-TIMEZONE:Europe/Berlin','REFRESH-INTERVAL;VALUE=DURATION:PT4H','X-PUBLISHED-TTL:PT4H'];
 foreach($rows as $row){
  $d=$row['data'];$start=ics_date($d['date']??null);if(!$start)continue;
  $end=ics_date($d['end_date']??null)??$start;if($end<$start)$end=$start;
  $uid=hash('sha256','ntc93-event:'.$row['slug']).'@ntc93.de';
  $stamp=isset($row['updated_at'])?(new DateTimeImmutable($row['updated_at'],new DateTimeZone('Europe/Berlin')))->setTimezone(new DateTimeZone('UTC'))->format('Ymd\THis\Z'):'20261127T000000Z';
  $lines[]='BEGIN:VEVENT';$lines[]='UID:'.$uid;$lines[]='DTSTAMP:'.$stamp;
  $startTime='';$endTime='';
  if(preg_match('/^([01]\d|2[0-3]):([0-5]\d)(?:\s*[–-]\s*((?:[01]\d|2[0-3]):[0-5]\d))?/',(string)($d['time']??''),$m)){
   $startTime=$m[1].':'.$m[2];$endTime=$m[3]??'';
  }
  if(preg_match('/^(?:[01]\d|2[0-3]):[0-5]\d$/D',(string)($d['end_time']??'')))$endTime=$d['end_time'];
  if($startTime!==''){
   [$h,$m]=array_map('intval',explode(':',$startTime));
   $st=$start->setTime($h,$m)->setTimezone(new DateTimeZone('UTC'));
   $lines[]='DTSTART:'.$st->format('Ymd\THis\Z');
   if($endTime!==''){
    [$h,$m]=array_map('intval',explode(':',$endTime));$et=$end->setTime($h,$m)->setTimezone(new DateTimeZone('UTC'));
    if($et>$st)$lines[]='DTEND:'.$et->format('Ymd\THis\Z');
   }
  }else{
   $lines[]='DTSTART;VALUE=DATE:'.$start->format('Ymd');
   $lines[]='DTEND;VALUE=DATE:'.$end->modify('+1 day')->format('Ymd');
  }
  $lines[]='SUMMARY:'.ics_escape((string)$row['title']);
  $lines[]='LOCATION:'.ics_escape((string)($d['venue']??''));
  $description=(string)($d['body']??'');
  if(!empty($d['status'])&&$d['status']!=='Bestätigt')$description.="\nStatus: ".$d['status'];
  $lines[]='DESCRIPTION:'.ics_escape($description);
  $lines[]='STATUS:'.(stripos((string)($d['status']??''),'voraussichtlich')!==false?'TENTATIVE':'CONFIRMED');
  $link=(string)($d['link']??'');
  if(str_starts_with($link,'/')&&!str_starts_with($link,'//'))$link='https://ntc93.de'.$link;
  if(filter_var($link,FILTER_VALIDATE_URL)&&in_array(parse_url($link,PHP_URL_SCHEME),['http','https'],true)&&!preg_match('/[\r\n]/',$link))$lines[]='URL:'.$link;
  $lines[]='END:VEVENT';
 }
 $lines[]='END:VCALENDAR';
 header('Content-Type: text/calendar; charset=utf-8');
 header('Content-Disposition: inline; filename="ntc93-termine.ics"');
 header('Cache-Control: public, max-age=300');
 foreach($lines as $line)echo ics_line($line);
 exit;
}

if (isset($_GET['public'])) {
 $kind=(string)$_GET['public'];
 if(!in_array($kind,['news','events','sponsors','notices'],true))stop(404,'Unbekannter Bereich.');
 if(!isset($types[$kind]))stop(404,'Unbekannter Bereich.');
 $q=run("SELECT slug,published_title AS title,published_data AS data,publish_at,position FROM cms_entries WHERE kind=? AND state!='archived' AND published_data IS NOT NULL AND publish_at<=NOW() ORDER BY position ASC,publish_at DESC,id DESC",[$kind]);
 $out=[];foreach($q as $row){$row['data']=json_decode($row['data'],true)??[];$out[]=$row;}
 if($kind==='events'&&!$firstAdmin)jsonout(['items'=>$eventSeed]);
 jsonout(['items'=>$out]);
}
session_name('NTC93_ADMIN');
session_set_cookie_params(['lifetime'=>0,'path'=>'/admin/','secure'=>true,'httponly'=>true,'samesite'=>'Strict']);
ini_set('session.use_strict_mode','1');session_start();
if(!isset($_SESSION['csrf']))$_SESSION['csrf']=bin2hex(random_bytes(32));
function csrf(): string{return '<input type="hidden" name="csrf" value="'.e($_SESSION['csrf']).'">';}
function redirect(string $to='/admin/'): never {header('Location: '.$to, true,303);exit;}
function audit(int $uid,string $action,string $detail): void {run('INSERT INTO cms_log(actor_id,action,detail) VALUES(?,?,?)',[$uid,$action,substr($detail,0,240)]);}
function strong_password(string $s):bool{return strlen($s)>=14 && strlen($s)<=200;}
function valid_login(string $s):bool{return preg_match('/^[a-zA-Z0-9._@+-]{3,100}$/D',$s)===1;}
function safe_url(string $s):bool{return $s==='' || (str_starts_with($s,'/')&&!str_starts_with($s,'//')&&!str_contains($s,'\\')&&!preg_match('/[\x00-\x20]/',$s)) || (filter_var($s,FILTER_VALIDATE_URL)!==false && in_array(parse_url($s,PHP_URL_SCHEME),['http','https'],true));}
function shell(string $title,string $content,?array $u=null): never {global $types;
 header('Content-Type: text/html; charset=utf-8');
 echo '<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>'.e($title).' | NTC Redaktion</title><link rel="stylesheet" href="/admin/admin.css"></head><body>';
 if($u){echo '<aside class="side"><a class="brand" href="/admin/"><strong>NTC 93</strong><small>Redaktion & Verwaltung</small></a><nav><a href="/admin/">Übersicht</a>';foreach($types as $key=>$t)echo '<a href="?area='.e($key).'">'.e($t[0]).'</a>';echo '<a href="?area=media">Medienbibliothek</a><a href="?area=matchcenter">Matchcenter</a>';if($u['role']==='admin')echo '<a href="?area=users">Benutzer & Rechte</a><a href="?area=log">Änderungsprotokoll</a>';echo '</nav><a class="public" href="/">Website ansehen ↗</a></aside><main><header><div><span class="overline">NTC 93 · REDAKTION</span><h1>'.e($title).'</h1></div><form method="post">'.csrf().'<input type="hidden" name="action" value="logout"><span>'.e($u['name']).' · '.e($u['role']).'</span> <button class="secondary">Abmelden</button></form></header>';}
 else echo '<main class="auth"><h1>'.e($title).'</h1>';
 echo $content.'</main></body></html>';exit;
}
$err='';$action=(string)($_POST['action']??'');
$count=(int)run('SELECT COUNT(*) FROM cms_users')->fetchColumn();
if($_SERVER['REQUEST_METHOD']==='POST' && !hash_equals($_SESSION['csrf'],(string)($_POST['csrf']??'')))stop(403,'Ungültige Anfrage.');
if($count===0){
 if(empty($c['setup_token'])||strlen((string)$c['setup_token'])<32)stop(503,'Sicherer Einrichtungsschlüssel fehlt.');
 if($action==='setup'){
  $login=trim((string)($_POST['login']??''));$name=trim((string)($_POST['name']??''));$pw=(string)($_POST['password']??'');
  if(!hash_equals((string)$c['setup_token'],(string)($_POST['token']??''))||!valid_login($login)||!strong_password($pw)||$name==='')$err='Einrichtung fehlgeschlagen. Schlüssel, Name und Passwort prüfen (mind. 14 Zeichen).';
  else{
   // Serialize the one-time setup so a second request cannot create another administrator.
   $lock=(int)run("SELECT GET_LOCK('ntc93_cms_initial_setup',5)")->fetchColumn();
   if($lock!==1)stop(503,'Einrichtung vorübergehend gesperrt.');
   try{if((int)run('SELECT COUNT(*) FROM cms_users')->fetchColumn()!==0)redirect();
    run('INSERT INTO cms_users(login,name,password_hash,role) VALUES(?,?,?,?)',[$login,$name,password_hash($pw,PASSWORD_DEFAULT),'admin']);}
   finally{run("SELECT RELEASE_LOCK('ntc93_cms_initial_setup')");}
   redirect();
  }
 }
 shell('NTC Redaktionssystem einrichten',($err?'<p class="error">'.e($err).'</p>':'').'<p>Erstes Administratorkonto mit dem privaten Einrichtungsschlüssel anlegen.</p><form method="post">'.csrf().'<input type="hidden" name="action" value="setup"><label>Einrichtungsschlüssel<input type="password" name="token" required autocomplete="off"></label><label>Name<input name="name" required></label><label>Benutzername<input name="login" required></label><label>Passwort (mind. 14 Zeichen)<input name="password" type="password" required minlength="14" autocomplete="new-password"></label><button>Konto anlegen</button></form>');
}
if($action==='login'){
 $login=trim((string)($_POST['login']??''));$pw=(string)($_POST['password']??'');
 $fp=hash('sha256',($_SERVER['REMOTE_ADDR']??'').'|'.strtolower($login));$now=time();
 run('INSERT IGNORE INTO cms_attempts(fingerprint,tries,window_start) VALUES(?,0,?)',[$fp,$now]);
 run('UPDATE cms_attempts SET tries=0,window_start=? WHERE fingerprint=? AND window_start<?',[$now,$fp,$now-900]);
 run('UPDATE cms_attempts SET tries=tries+1 WHERE fingerprint=?',[$fp]);
 $tries=(int)run('SELECT tries FROM cms_attempts WHERE fingerprint=?',[$fp])->fetchColumn();
 $u=run('SELECT * FROM cms_users WHERE login=? AND active=1',[$login])->fetch();
 if($tries<=8 && $u && password_verify($pw,$u['password_hash'])){
  run('DELETE FROM cms_attempts WHERE fingerprint=?',[$fp]);session_regenerate_id(true);$_SESSION['uid']=(int)$u['id'];$_SESSION['last']=time();$_SESSION['csrf']=bin2hex(random_bytes(32));redirect();
 }
 $err='Anmeldung fehlgeschlagen oder vorübergehend gesperrt.';
}
if(isset($_SESSION['uid']) && time()-(int)($_SESSION['last']??0)>3600)unset($_SESSION['uid']);
$u=isset($_SESSION['uid'])?run('SELECT * FROM cms_users WHERE id=? AND active=1',[(int)$_SESSION['uid']])->fetch():false;
if(!$u)shell('Anmeldung',($err?'<p class="error">'.e($err).'</p>':'').'<form method="post">'.csrf().'<input type="hidden" name="action" value="login"><label>Benutzername<input name="login" required autocomplete="username"></label><label>Passwort<input type="password" name="password" required autocomplete="current-password"></label><button>Anmelden</button></form>');
$_SESSION['last']=time();$uid=(int)$u['id'];$admin=$u['role']==='admin';$publish=$u['role']!=='author';
if($action==='logout'){$_SESSION=[];session_destroy();redirect();}
$area=(string)($_GET['area']??'');$id=(int)($_GET['id']??0);
if(in_array($area,['users','log','settings','menus'],true)&&!$admin)stop(403,'Keine Berechtigung.');
if($action==='save' || $action==='archive'){
 $kind=(string)($_POST['kind']??'');$eid=(int)($_POST['id']??0);
 if(!isset($types[$kind])||(!$admin&&in_array($kind,['settings','menus'],true)))stop(403,'Keine Berechtigung.');
 $db->beginTransaction();
 try {
  $old=$eid?run('SELECT * FROM cms_entries WHERE id=? AND kind=? FOR UPDATE',[$eid,$kind])->fetch():null;
  if($eid&&!$old)throw new RuntimeException('Eintrag fehlt.');
  if($old&&!$publish&&(int)$old['owner_id']!==$uid)throw new RuntimeException('Keine Berechtigung.');
  if($old)run('INSERT INTO cms_revisions(entry_id,actor_id,snapshot) VALUES(?,?,?)',[$eid,$uid,json_encode($old,JSON_UNESCAPED_UNICODE)]);
  if($action==='archive'){
   if(!$publish||!$old)throw new RuntimeException('Keine Berechtigung.');
   run("UPDATE cms_entries SET state='archived',updated_by=? WHERE id=?",[$uid,$eid]);audit($uid,'archiviert',$old['title']);
  }else{
   $title=trim((string)($_POST['title']??''));$slug=trim((string)($_POST['slug']??''));$position=(int)($_POST['position']??0);
   if($title===''||strlen($title)>240||!preg_match('/^[a-z0-9][a-z0-9-]{0,179}$/D',$slug))throw new RuntimeException('Titel oder URL-Kürzel ungültig.');
   $data=[];foreach($types[$kind][1] as $k=>$label){$v=trim((string)($_POST['field'][$k]??''));if(strlen($v)>100000)throw new RuntimeException('Inhalt zu lang.');if(in_array($k,['image','link'],true)&&!safe_url($v))throw new RuntimeException('Ungültige URL.');$data[$k]=$v;}
   $payload=json_encode($data,JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);
   $doPublish=$publish&&($_POST['intent']??'')==='publish';
   if($old&&$old['published_data']!==null&&$slug!==$old['slug'])throw new RuntimeException('URL-Kürzel bereits veröffentlichter Inhalte nicht ändern.');
   $when=null;if($doPublish){$when=trim((string)($_POST['publish_at']??''));if($when==='')$when=date('Y-m-d H:i:s');else{$dt=DateTimeImmutable::createFromFormat('Y-m-d\TH:i',$when);if(!$dt)throw new RuntimeException('Ungültiges Veröffentlichungsdatum.');$when=$dt->format('Y-m-d H:i:s');}}
   if(!$old){run("INSERT INTO cms_entries(kind,slug,title,data,state,published_data,published_title,publish_at,position,owner_id,updated_by) VALUES(?,?,?,?,?,?,?,?,?,?,?)",[$kind,$slug,$title,$payload,$doPublish?'published':'draft',$doPublish?$payload:null,$doPublish?$title:null,$when,$position,$uid,$uid]);$eid=(int)$db->lastInsertId();}
   elseif($doPublish){run("UPDATE cms_entries SET slug=?,title=?,data=?,state='published',published_data=?,published_title=?,publish_at=?,position=?,updated_by=? WHERE id=?",[$slug,$title,$payload,$payload,$title,$when,$position,$uid,$eid]);}
   else{run("UPDATE cms_entries SET slug=?,title=?,data=?,state=IF(state='archived','archived','draft'),position=?,updated_by=? WHERE id=?",[$slug,$title,$payload,$position,$uid,$eid]);}
   audit($uid,$doPublish?'veröffentlicht':'gespeichert',$title);
  }
  $db->commit();redirect('?area='.rawurlencode($kind));
 }catch(Throwable $ex){$db->rollBack();$err=$ex instanceof RuntimeException&&!($ex instanceof PDOException)?$ex->getMessage():'Speichern fehlgeschlagen (z. B. doppeltes URL-Kürzel).';$area=$kind;$id=$eid;}
}
if($action==='user_create'&&$admin){
 $login=trim((string)($_POST['login']??''));$name=trim((string)($_POST['name']??''));$pw=(string)($_POST['password']??'');$role=(string)($_POST['role']??'');
 if(!valid_login($login)||!strong_password($pw)||$name===''||!in_array($role,['admin','editor','author'],true))$err='Benutzerdaten ungültig.';
 else try{run('INSERT INTO cms_users(login,name,password_hash,role) VALUES(?,?,?,?)',[$login,$name,password_hash($pw,PASSWORD_DEFAULT),$role]);audit($uid,'Benutzer angelegt',$login);redirect('?area=users');}catch(Throwable){$err='Benutzer konnte nicht angelegt werden.';}
}
if($action==='user_toggle'&&$admin){$target=(int)($_POST['id']??0);if($target!==$uid){run('UPDATE cms_users SET active=1-active WHERE id=?',[$target]);audit($uid,'Benutzerstatus geändert',(string)$target);}redirect('?area=users');}
if($action==='password'){
 $pw=(string)($_POST['password']??'');
 if(!password_verify((string)($_POST['current']??''),$u['password_hash'])||!strong_password($pw))$err='Passwort nicht geändert.';
 else{run('UPDATE cms_users SET password_hash=? WHERE id=?',[password_hash($pw,PASSWORD_DEFAULT),$uid]);audit($uid,'Passwort geändert','');redirect();}
}
if($action==='upload'){
 $f=$_FILES['file']??null;$allowed=['image/jpeg','image/png','image/webp','image/gif','application/pdf'];
 if(!$f||$f['error']!==UPLOAD_ERR_OK||$f['size']>5*1024*1024||!is_uploaded_file($f['tmp_name']))$err='Datei fehlt oder größer als 5 MB.';
 else{
  $mime=(new finfo(FILEINFO_MIME_TYPE))->file($f['tmp_name']);
  if(!in_array($mime,$allowed,true)||($mime!=='application/pdf'&&!@getimagesize($f['tmp_name'])))$err='Dateiformat nicht zulässig.';
  else{run('INSERT INTO cms_media(name,mime,bytes,alt,owner_id) VALUES(?,?,?,?,?)',[substr(basename($f['name']),0,240),$mime,file_get_contents($f['tmp_name']),substr((string)($_POST['alt']??''),0,240),$uid]);audit($uid,'Medium hochgeladen',basename($f['name']));redirect('?area=media');}
 }
 $area='media';
}
$msg=$err?'<p class="error">'.e($err).'</p>':'';
if(isset($types[$area])){
 [$label,$fields]=$types[$area];$record=$id?run('SELECT * FROM cms_entries WHERE id=? AND kind=?',[$id,$area])->fetch():null;
 if($id&&!$record)stop(404,'Eintrag fehlt.');
 if($record&&!$publish&&(int)$record['owner_id']!==$uid)stop(403,'Keine Berechtigung.');
 if(isset($_GET['edit'])||$record||$err){
  $data=json_decode($record['data']??'{}',true)??[];
  $form='<a class="back" href="?area='.e($area).'">← Zur Übersicht</a><form method="post" class="panel">'.csrf().'<input type="hidden" name="action" value="save"><input type="hidden" name="kind" value="'.e($area).'"><input type="hidden" name="id" value="'.(int)($record['id']??0).'"><label>Titel<input name="title" value="'.e($record['title']??'').'" required maxlength="240"></label><label>URL-Kürzel (klein, Bindestriche)<input name="slug" value="'.e($record['slug']??'').'" required pattern="[a-z0-9][a-z0-9-]*" maxlength="180"></label>';
  foreach($fields as $k=>$l){$v=e($data[$k]??'');$form.='<label>'.e($l).(in_array($k,$long,true)?'<textarea name="field['.e($k).']" rows="'.($k==='body'?10:3).'">'.$v.'</textarea>':'<input name="field['.e($k).']" value="'.$v.'">').'</label>';}
  $form.='<label>Reihenfolge<input type="number" name="position" value="'.(int)($record['position']??0).'"></label>';
  if($publish)$form.='<label>Veröffentlichen ab (leer = sofort)<input type="datetime-local" name="publish_at" value="'.e(isset($record['publish_at'])?str_replace(' ','T',substr($record['publish_at'],0,16)):'').'"></label>';
  $form.='<div class="actions"><button name="intent" value="draft" class="secondary">Entwurf speichern</button>'.($publish?'<button name="intent" value="publish">Veröffentlichen</button>':'').'</div></form>';
  if($record&&$publish){$form.='<form method="post" class="panel">'.csrf().'<input type="hidden" name="kind" value="'.e($area).'"><input type="hidden" name="id" value="'.$id.'"><button class="secondary" name="action" value="archive">Archivieren / Veröffentlichung zurückziehen</button></form>';}
  if($record){$hist=run('SELECT r.created_at,u.name FROM cms_revisions r JOIN cms_users u ON u.id=r.actor_id WHERE entry_id=? ORDER BY r.id DESC LIMIT 15',[$id]);$form.='<div class="panel"><h2>Versionsverlauf</h2>';foreach($hist as $h)$form.='<p>'.e($h['created_at']).' · '.e($h['name']).'</p>';$form.='</div>';}
  shell($label.' bearbeiten',$msg.$form,$u);
 }
 $list=run('SELECT id,title,state,published_data IS NOT NULL AS live,publish_at,updated_at FROM cms_entries WHERE kind=?'.($publish?'':' AND owner_id=?').' ORDER BY updated_at DESC',$publish?[$area]:[$area,$uid]);
 $body=$msg.'<a class="button" href="?area='.e($area).'&edit=1">+ Neu anlegen</a><div class="panel"><table><thead><tr><th>Titel</th><th>Status</th><th>Geändert</th></tr></thead><tbody>';
 foreach($list as $row)$body.='<tr><td><a href="?area='.e($area).'&id='.$row['id'].'">'.e($row['title']).'</a></td><td>'.e($row['state']==='archived'?'Archiviert':($row['state']==='draft'?($row['live']?'Entwurf · frühere Version online':'Entwurf'):'Veröffentlicht / geplant')).'</td><td>'.e($row['updated_at']).'</td></tr>';
 shell($label,$body.'</tbody></table><p class="muted">Nur im CMS angelegte Inhalte. Importierte Website-Inhalte werden zunächst separat geführt. In den angebundenen Bereichen sind veröffentlichte Daten öffentlich. Keine Zugangsdaten oder vertraulichen Mitgliederdaten eintragen.</p></div>',$u);
}
if($area==='media'){
 $body=$msg.'<form class="panel" method="post" enctype="multipart/form-data">'.csrf().'<input type="hidden" name="action" value="upload"><p>Öffentliche Website-Medien, max. 5 MB. Keine vertraulichen Dokumente hochladen.</p><label>Datei (JPG, PNG, WebP, GIF, PDF)<input type="file" name="file" required></label><label>Alternativtext<input name="alt"></label><button>Hochladen</button></form><div class="media-grid">';
 foreach(run('SELECT id,name,mime,alt FROM cms_media ORDER BY id DESC LIMIT 200') as $m){$url='/admin/?media='.$m['id'];$body.='<div class="panel">'.(str_starts_with($m['mime'],'image/')?'<img src="'.e($url).'" alt="'.e($m['alt']).'">':'<a href="'.e($url).'">PDF öffnen</a>').'<strong>'.e($m['name']).'</strong><label>Medien-URL<input readonly value="'.e($url).'"></label></div>';}
 shell('Medienbibliothek',$body.'</div>',$u);
}
if($area==='users'){
 $body=$msg.'<div class="panel"><h2>Benutzer anlegen</h2><form method="post">'.csrf().'<input type="hidden" name="action" value="user_create"><label>Name<input name="name" required></label><label>Benutzername<input name="login" required></label><label>Rolle<select name="role"><option value="author">Autor – Entwürfe</option><option value="editor">Redaktion – Veröffentlichung</option><option value="admin">Administrator</option></select></label><label>Passwort (mind. 14 Zeichen)<input name="password" type="password" required minlength="14" autocomplete="new-password"></label><button>Benutzer anlegen</button></form></div><div class="panel"><table>';
 foreach(run('SELECT id,login,name,role,active FROM cms_users ORDER BY id') as $m){$body.='<tr><td>'.e($m['name']).'<br><small>'.e($m['login']).'</small></td><td>'.e($m['role']).'</td><td>'.($m['active']?'Aktiv':'Gesperrt').'</td><td>'.($m['id']!=$uid?'<form method="post">'.csrf().'<input type="hidden" name="id" value="'.$m['id'].'"><button class="secondary" name="action" value="user_toggle">Status ändern</button></form>':'').'</td></tr>';}
 shell('Benutzer & Rechte',$body.'</table></div>',$u);
}
if($area==='log'){
 $body='<div class="panel"><table><tr><th>Zeit</th><th>Benutzer</th><th>Aktion</th><th>Inhalt</th></tr>';foreach(run('SELECT l.*,u.name FROM cms_log l JOIN cms_users u ON l.actor_id=u.id ORDER BY l.id DESC LIMIT 200') as $m)$body.='<tr><td>'.e($m['created_at']).'</td><td>'.e($m['name']).'</td><td>'.e($m['action']).'</td><td>'.e($m['detail']).'</td></tr>';shell('Änderungsprotokoll',$body.'</table></div>',$u);
}
if($area==='matchcenter'){
 $data=json_decode(@file_get_contents(dirname(__DIR__).'/matches.json')?:'{}',true);
 shell('Matchcenter','<div class="panel"><h2>nuLiga-Datenimport</h2><p>Datenstand: '.e($data['updated']??'Noch nicht verfügbar').'</p><p>Begegnungen: '.count($data['matches']??[]).'</p><p>Aktualisierung über den bestehenden GitHub-Workflow alle vier Stunden vorgesehen. Ergebnisse werden nicht manuell überschrieben.</p><a class="button" href="/matchcenter/">Matchcenter öffnen ↗</a></div>',$u);
}
$body=$msg.'<div class="stats">';
foreach($types as $k=>$t){if(!$admin&&in_array($k,['settings','menus'],true))continue;$n=(int)run('SELECT COUNT(*) FROM cms_entries WHERE kind=? AND state=?',[$k,'draft'])->fetchColumn();$body.='<a class="panel stat" href="?area='.e($k).'"><small>'.e($t[0]).'</small><strong>'.$n.'</strong><span>Entwürfe</span></a>';}
$body.='</div><div class="panel"><h2>Mein Konto</h2><form method="post">'.csrf().'<input type="hidden" name="action" value="password"><label>Aktuelles Passwort<input type="password" name="current" required autocomplete="current-password"></label><label>Neues Passwort<input type="password" name="password" required minlength="14" autocomplete="new-password"></label><button>Passwort ändern</button></form></div><p class="muted">Redaktionsgrundlage · Die öffentliche Ausgabe von Nachrichten, Sponsoren, Terminen und Hinweisen ist angebunden. Weitere Bereiche und Altinhalte folgen separat.</p>';
shell('Übersicht',$body,$u);
