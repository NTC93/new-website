<?php
// Copy to admin/private/config.php on the isolated preview server, never commit the real values.
return [
 'dsn' => 'mysql:host=localhost;dbname=DATABASE;charset=utf8mb4',
 'db_user' => 'DATABASE_USER',
 'db_password' => 'DATABASE_PASSWORD',
 'setup_token' => 'REPLACE_WITH_RANDOM_TOKEN_AT_LEAST_32_CHARACTERS',
];
