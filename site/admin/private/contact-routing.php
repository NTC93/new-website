<?php
declare(strict_types=1);
function contact_defaults(): array {
 return [
  'general'=>['Allgemeine Anfrage',''],
  'chair'=>['1. Vorsitzender','vorstand@ntc93.de'],
  'deputy'=>['2. Vorsitzender','vorstand2@ntc93.de'],
  'sport'=>['Sport & Mannschaften','sportwart@ntc93.de'],
  'youth'=>['Jugend & Jugendtraining','jugendwart@ntc93.de'],
  'finance'=>['Finanzen & Beiträge','kassenwart@ntc93.de'],
  'hall'=>['Tennishalle & Hallenbetrieb','halle@ntc93.de']
 ];
}
function contact_address(string $v): bool {
 return strlen($v)<=254 && !preg_match('/[\r\n\x00]/',$v) && filter_var($v,FILTER_VALIDATE_EMAIL)!==false;
}
function contact_init(PDO $db): void {
 $db->exec("CREATE TABLE IF NOT EXISTS cms_contact_routes (route_key VARCHAR(32) PRIMARY KEY, recipient VARCHAR(254) NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
 $db->exec("CREATE TABLE IF NOT EXISTS cms_contact_limits (fingerprint CHAR(64) PRIMARY KEY, tries INT NOT NULL, window_start INT NOT NULL) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4");
}
function contact_routes(PDO $db): array {
 $routes=contact_defaults();
 foreach($db->query('SELECT route_key,recipient FROM cms_contact_routes') as $row){
  $key=$row['route_key'];$address=$row['recipient'];
  if($key!=='general' && isset($routes[$key]) && ($address==='' || contact_address($address)))$routes[$key][1]=$address;
 }
 return $routes;
}
