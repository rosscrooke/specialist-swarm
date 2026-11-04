<?php
/**
 * Synthetic CRM — minimal MCP server (streamable HTTP, stateless, JSON-RPC).
 *
 * Exposes past deals from past-wins.json to the Pricing Specialist.
 * Tools: search_past_deals, get_deal
 *
 * Auth: Authorization: Bearer <token from config.php>
 * Synthetic data only. Never put real customer data here.
 */

declare(strict_types=1);

const SERVER_NAME = 'synthetic-crm';
const SERVER_VERSION = '0.1.0';
const DEFAULT_PROTOCOL = '2025-03-26';

function respond(int $status, ?array $body = null): never
{
    http_response_code($status);
    if ($body !== null) {
        header('Content-Type: application/json');
        echo json_encode($body, JSON_UNESCAPED_UNICODE | JSON_UNESCAPED_SLASHES);
    }
    exit;
}

function rpc_result(mixed $id, array $result): never
{
    respond(200, ['jsonrpc' => '2.0', 'id' => $id, 'result' => $result]);
}

function rpc_error(mixed $id, int $code, string $message): never
{
    respond(200, ['jsonrpc' => '2.0', 'id' => $id, 'error' => ['code' => $code, 'message' => $message]]);
}

function bearer_token(): string
{
    $h = $_SERVER['HTTP_AUTHORIZATION'] ?? $_SERVER['REDIRECT_HTTP_AUTHORIZATION'] ?? '';
    if ($h === '' && function_exists('getallheaders')) {
        foreach (getallheaders() as $k => $v) {
            if (strcasecmp($k, 'Authorization') === 0) {
                $h = $v;
            }
        }
    }
    return preg_match('/^Bearer\s+(.+)$/i', $h, $m) ? trim($m[1]) : '';
}

function load_deals(): array
{
    $data = json_decode((string) file_get_contents(__DIR__ . '/past-wins.json'), true);
    return $data['comparable_deals'] ?? [];
}

function tools(): array
{
    return [
        [
            'name' => 'search_past_deals',
            'description' => 'Search past deals (wins and losses) in the CRM. All filters are optional '
                . 'and combined with AND. Returns discount, term, payment terms, competitors and '
                . 'why we won or lost. Use it to anchor discount recommendations on comparable deals.',
            'inputSchema' => [
                'type' => 'object',
                'properties' => [
                    'industry' => ['type' => 'string', 'description' => 'Case-insensitive substring of the industry, e.g. "industrial".'],
                    'competitor' => ['type' => 'string', 'description' => 'Case-insensitive competitor name, e.g. "Snowflake".'],
                    'min_annual_usd' => ['type' => 'number', 'description' => 'Minimum annual deal size in USD.'],
                    'max_annual_usd' => ['type' => 'number', 'description' => 'Maximum annual deal size in USD.'],
                    'outcome' => ['type' => 'string', 'enum' => ['won', 'lost'], 'description' => 'Only won or only lost deals.'],
                ],
            ],
        ],
        [
            'name' => 'get_deal',
            'description' => 'Get the full record of one past deal by customer name (case-insensitive substring).',
            'inputSchema' => [
                'type' => 'object',
                'properties' => [
                    'customer' => ['type' => 'string', 'description' => 'Customer name, e.g. "Initech".'],
                ],
                'required' => ['customer'],
            ],
        ],
    ];
}

function tool_text(mixed $payload, bool $isError = false): array
{
    return [
        'content' => [['type' => 'text', 'text' => is_string($payload)
            ? $payload
            : json_encode($payload, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE)]],
        'isError' => $isError,
    ];
}

function call_tool(string $name, array $args): array
{
    $deals = load_deals();

    if ($name === 'search_past_deals') {
        $hits = array_values(array_filter($deals, function (array $d) use ($args): bool {
            $won = ($d['won_on'] ?? null) !== null;
            if (isset($args['industry']) && stripos($d['industry'] ?? '', (string) $args['industry']) === false) {
                return false;
            }
            if (isset($args['competitor'])) {
                $match = false;
                foreach ($d['primary_competitors'] ?? [] as $c) {
                    if (stripos($c, (string) $args['competitor']) !== false) {
                        $match = true;
                    }
                }
                if (!$match) {
                    return false;
                }
            }
            if (isset($args['outcome']) && ($args['outcome'] === 'won') !== $won) {
                return false;
            }
            // Lost deals have size 0, so size filters only apply to won deals.
            if ($won && isset($args['min_annual_usd']) && $d['deal_size_annual_usd'] < $args['min_annual_usd']) {
                return false;
            }
            if ($won && isset($args['max_annual_usd']) && $d['deal_size_annual_usd'] > $args['max_annual_usd']) {
                return false;
            }
            return true;
        }));
        return tool_text(['count' => count($hits), 'deals' => $hits]);
    }

    if ($name === 'get_deal') {
        $q = (string) ($args['customer'] ?? '');
        if ($q === '') {
            return tool_text('Missing required argument: customer', true);
        }
        foreach ($deals as $d) {
            if (stripos($d['customer'] ?? '', $q) !== false) {
                return tool_text($d);
            }
        }
        return tool_text("No deal found for customer matching \"$q\".", true);
    }

    return tool_text("Unknown tool: $name", true);
}

// ---- Request handling ------------------------------------------------------

if (($_SERVER['REQUEST_METHOD'] ?? '') !== 'POST') {
    header('Allow: POST');
    respond(405, ['error' => 'Use POST with a JSON-RPC body.']);
}

$configFile = __DIR__ . '/config.php';
$config = is_file($configFile) ? require $configFile : [];
$expected = (string) ($config['token'] ?? '');
if ($expected === '' || $expected === 'CHANGE-ME') {
    respond(500, ['error' => 'Server not configured: create config.php with a token.']);
}
if (!hash_equals($expected, bearer_token())) {
    header('WWW-Authenticate: Bearer');
    respond(401, ['error' => 'Unauthorized']);
}

$msg = json_decode((string) file_get_contents('php://input'), true);
if (!is_array($msg) || ($msg['jsonrpc'] ?? '') !== '2.0') {
    rpc_error(null, -32700, 'Parse error or not JSON-RPC 2.0');
}

$id = $msg['id'] ?? null;
$method = (string) ($msg['method'] ?? '');
$params = is_array($msg['params'] ?? null) ? $msg['params'] : [];

// Notifications carry no id and expect no JSON-RPC response.
if (!array_key_exists('id', $msg)) {
    respond(202);
}

switch ($method) {
    case 'initialize':
        rpc_result($id, [
            'protocolVersion' => (string) ($params['protocolVersion'] ?? DEFAULT_PROTOCOL),
            'capabilities' => ['tools' => ['listChanged' => false]],
            'serverInfo' => ['name' => SERVER_NAME, 'version' => SERVER_VERSION],
        ]);
    case 'ping':
        rpc_result($id, []);
    case 'tools/list':
        rpc_result($id, ['tools' => tools()]);
    case 'tools/call':
        $args = is_array($params['arguments'] ?? null) ? $params['arguments'] : [];
        rpc_result($id, call_tool((string) ($params['name'] ?? ''), $args));
    default:
        rpc_error($id, -32601, "Method not found: $method");
}
