<?php
declare(strict_types=1);
ini_set('display_errors','0');
header('Content-Type: application/json; charset=utf-8');
header('Cache-Control: no-store');
header('X-Content-Type-Options: nosniff');
header('X-Robots-Tag: noindex, nofollow');
header("Content-Security-Policy: default-src 'none'; frame-ancestors 'none'");
function reply(int $status,array $body): never {http_response_code($status);echo json_encode($body,JSON_UNESCAPED_UNICODE|JSON_INVALID_UTF8_SUBSTITUTE);exit;}
function fail(int $status,string $msg): never {reply($status,['ok'=>false,'message'=>$msg]);}
$method=$_SERVER['REQUEST_METHOD']??'GET';
if(!in_array($method,['GET','POST'],true))fail(405,'Methode nicht erlaubt.');
if(($_SERVER['HTTP_SEC_FETCH_SITE']??'')==='cross-site')fail(403,'Ungültige Anfrage.');
session_name('NTC93_CONTACT');
session_set_cookie_params(['lifetime'=>0,'path'=>'/contact-api.php','secure'=>true,'httponly'=>true,'samesite'=>'Strict']);
ini_set('session.use_strict_mode','1');
session_start();
if($method==='GET'){
 $_SESSION['contact_token']=bin2hex(random_bytes(32));
 $_SESSION['contact_started']=time();
 reply(200,['ok'=>true,'token'=>$_SESSION['contact_token']]);
}
if((int)($_SERVER['CONTENT_LENGTH']??0)>35000)fail(413,'Die Nachricht ist zu lang.');
if(empty($_SESSION['contact_token'])||!is_string($_POST['token']??null)||!hash_equals($_SESSION['contact_token'],$_POST['token'])||time()-(int)($_SESSION['contact_started']??0)>7200)fail(403,'Bitte lade das Formular neu und versuche es erneut.');
if(time()-(int)($_SESSION['contact_started']??0)<2)fail(429,'Bitte versuche es in einigen Sekunden erneut.');
function field(string $key): string {return is_string($_POST[$key]??null)?trim($_POST[$key]):'';}
if(field('website')!=='')fail(400,'Die Anfrage konnte nicht verarbeitet werden.');
$name=field('name');$email=field('email');$phone=field('phone');$subject=field('subject');$message=field('message');$route=field('route');
$configFile=__DIR__.'/admin/private/config.php';
require_once __DIR__.'/admin/private/contact-routing.php';
if($name===''||strlen($name)>200||!contact_address($email)||strlen($phone)>100||$subject===''||strlen($subject)>250||strlen($message)<5||strlen($message)>12000||!isset(contact_defaults()[$route])||field('privacy')!=='1')fail(422,'Bitte prüfe alle Pflichtfelder und die E-Mail-Adresse.');
if(preg_match('/[\x00-\x1f\x7f]/',$name.$subject.$phone)||str_contains($message,"\0")||!preg_match('//u',$name.$subject.$message.$phone))fail(422,'Ungültige Zeichen in der Anfrage.');
if(!is_file($configFile))fail(503,'Das Kontaktformular ist vorübergehend nicht verfügbar.');
try{
 $c=require $configFile;
 $db=new PDO($c['dsn'],$c['db_user'],$c['db_password']??'',[PDO::ATTR_ERRMODE=>PDO::ERRMODE_EXCEPTION,PDO::ATTR_DEFAULT_FETCH_MODE=>PDO::FETCH_ASSOC,PDO::ATTR_EMULATE_PREPARES=>false]);
 contact_init($db);
 $routes=contact_routes($db);
 $secret=(string)($c['setup_token']??$c['db_password']??'');
 if(strlen($secret)<16)throw new RuntimeException('missing rate key');
 $fp=hash_hmac('sha256','contact|'.($_SERVER['REMOTE_ADDR']??'unknown'),$secret);$now=time();
 $db->prepare('DELETE FROM cms_contact_limits WHERE window_start<?')->execute([$now-86400]);
 $db->prepare('INSERT INTO cms_contact_limits(fingerprint,tries,window_start) VALUES(?,1,?) ON DUPLICATE KEY UPDATE tries=IF(window_start<?,1,tries+1),window_start=IF(window_start<?,VALUES(window_start),window_start)')->execute([$fp,$now,$now-3600,$now-3600]);
 $q=$db->prepare('SELECT tries FROM cms_contact_limits WHERE fingerprint=?');$q->execute([$fp]);
 if((int)$q->fetchColumn()>5)fail(429,'Zu viele Anfragen. Bitte versuche es später erneut.');
 $central='info@ntc93.de';[$label,$additional]=$routes[$route];
 $subjectLine='=?UTF-8?B?'.base64_encode('NTC Kontakt: '.$label).'?=';
 $headers=['From'=>'NTC 93 Website <'.$central.'>','Reply-To'=>$email,'MIME-Version'=>'1.0','Content-Type'=>'text/plain; charset=UTF-8','Content-Transfer-Encoding'=>'8bit'];
 if($additional!==''&&strcasecmp($additional,$central)!==0)$headers['Cc']=$additional;
 $body="Neue Anfrage über das NTC-Kontaktformular\n\nBereich: ".$label."\nName: ".$name."\nE-Mail: ".$email."\nTelefon: ".($phone?:'nicht angegeben')."\nBetreff: ".$subject."\n\n".$message."\n";
 // Fixed recipient and sender, only validated reply address and admin-configured CC.
 if(!mail($central,$subjectLine,$body,$headers)){error_log('NTC contact: mail transport rejected message');fail(503,'Die Nachricht konnte nicht versendet werden. Bitte versuche es später erneut.');}
 unset($_SESSION['contact_token'],$_SESSION['contact_started']);
 reply(200,['ok'=>true,'message'=>'Vielen Dank! Deine Nachricht wurde versendet. Wir melden uns bei dir.']);
}catch(Throwable $ex){error_log('NTC contact: '.get_class($ex));fail(503,'Das Kontaktformular ist vorübergehend nicht verfügbar. Bitte versuche es später erneut.');}
