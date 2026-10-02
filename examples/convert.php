<?php
declare(strict_types=1);

/** Call from your authenticated backend, after checking the user's upload and quota.
 * Configure DOCBRIDGE_URL and DOCBRIDGE_API_KEY in your backend environment.
 * Returns file bytes; do not expose the service API key to the browser.
 */
function docbridgeConvert(string $path, string $source, string $target, string $language = 'eng'): string
{
    $key = getenv('DOCBRIDGE_API_KEY');
    $base = getenv('DOCBRIDGE_URL') ?: 'http://127.0.0.1:8080';
    if (!$key || !is_file($path) || filesize($path) > 20 * 1024 * 1024) {
        throw new RuntimeException('API key missing or input file invalid.');
    }
    $query = http_build_query(['source' => $source, 'target' => $target,
                              'language' => $language, 'ocr' => 'auto']);
    $request = curl_init(rtrim($base, '/') . '/v1/convert?' . $query);
    curl_setopt_array($request, [
        CURLOPT_POST => true,
        CURLOPT_POSTFIELDS => file_get_contents($path),
        CURLOPT_HTTPHEADER => ['Authorization: Bearer ' . $key, 'Content-Type: application/octet-stream'],
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_TIMEOUT => 200,
        CURLOPT_FOLLOWLOCATION => false,
    ]);
    try {
        $body = curl_exec($request);
        $status = curl_getinfo($request, CURLINFO_RESPONSE_CODE);
        if ($body === false || $status !== 200) {
            throw new RuntimeException('DocBridge conversion failed with HTTP status ' . $status);
        }
        return $body;
    } finally {
        curl_close($request);
    }
}

// Example in your backend:
// $pdf = docbridgeConvert($validatedUploadPath, 'docx', 'pdf');
// header('Content-Type: application/pdf');
// header('Content-Disposition: attachment; filename="converted.pdf"');
// header('Cache-Control: no-store');
// echo $pdf;
