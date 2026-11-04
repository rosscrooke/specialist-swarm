<?php
// Copy to config.php and set a long random token (e.g. `openssl rand -hex 32`).
// config.php is gitignored. The same token goes into the Vault credential
// (static_bearer) that the Managed Agents session uses.
return [
    'token' => 'CHANGE-ME',
];
