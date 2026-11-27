<?php
declare(strict_types=1);
// Included only by the authenticated admin application; never called directly.
function import_website_seed(int $actor): string {
 global $db,$types;
 $file=__DIR__.'/private/content-seed.json';
 if(!is_file($file))return 'Website-Importdatei noch nicht bereitgestellt.';
 $hash=hash_file('sha256',$file);
 if(!$hash)return 'Importdatei nicht lesbar.';
 if(run('SELECT 1 FROM cms_import_runs WHERE fingerprint=?',[$hash])->fetchColumn())return '';
 if((int)run("SELECT GET_LOCK('ntc93_website_seed',1)")->fetchColumn()!==1)return 'Website-Import läuft bereits.';
 try{
  if(run('SELECT 1 FROM cms_import_runs WHERE fingerprint=?',[$hash])->fetchColumn())return '';
  $seed=json_decode(file_get_contents($file),true,512,JSON_THROW_ON_ERROR);
  if(($seed['version']??0)!==1||!is_array($seed['entries']??null)||!is_array($seed['media']??null))throw new RuntimeException('Ungültige Importdatei.');
  $db->beginTransaction();$entries=0;$media=0;
  $insert=$db->prepare("INSERT INTO cms_entries(kind,slug,title,data,state,published_data,published_title,publish_at,position,owner_id,updated_by) VALUES(?,?,?,?,'published',?,?,?,?,?,?) ON DUPLICATE KEY UPDATE id=id");
  foreach($seed['entries'] as $row){
   $kind=$row['kind']??'';$slug=$row['slug']??'';$title=$row['title']??'';
   if(!isset($types[$kind])||!preg_match('/^[a-z0-9][a-z0-9-]{0,179}$/D',$slug)||!is_string($title)||$title==='')continue;
   $payload=json_encode($row['data'],JSON_UNESCAPED_UNICODE|JSON_THROW_ON_ERROR);
   $insert->execute([$kind,$slug,$title,$payload,$payload,$title,$row['publish_at'],(int)$row['position'],$actor,$actor]);
   $entries+=$insert->rowCount()>0?1:0;
  }
  $insertMedia=$db->prepare("INSERT INTO cms_import_media(url,name,mime,alt,size) VALUES(?,?,?,?,?) ON DUPLICATE KEY UPDATE id=id");
  $root=realpath(dirname(__DIR__).'/media');
  foreach($seed['media'] as $m){
   $url=$m['url']??'';
   if(!is_string($url)||!str_starts_with($url,'/media/')||str_contains($url,'..')||str_contains($url,'\\'))continue;
   $local=realpath(dirname(__DIR__).$url);
   if(!$local||!$root||!str_starts_with($local,$root.DIRECTORY_SEPARATOR)||!is_file($local))continue;
   $insertMedia->execute([$url,$m['name'],$m['mime'],$m['alt'],(int)$m['size']]);
   $media+=$insertMedia->rowCount()>0?1:0;
  }
  run('INSERT INTO cms_import_runs(fingerprint,entry_count,media_count) VALUES(?,?,?)',[$hash,$entries,$media]);
  run('INSERT INTO cms_log(actor_id,action,detail) VALUES(?,?,?)',[$actor,'Website-Import',"$entries Inhalte, $media Medien"]);
  $db->commit();
  return "Website-Import abgeschlossen: $entries neue Inhalte, $media Medien. Bereits gepflegte Einträge blieben unverändert.";
 }catch(Throwable $ex){
  if($db->inTransaction())$db->rollBack();
  error_log('NTC website seed import: '.$ex->getMessage());
  return 'Website-Import konnte nicht abgeschlossen werden. Bestehende Daten wurden nicht verändert.';
 }finally{run("SELECT RELEASE_LOCK('ntc93_website_seed')");}
}
