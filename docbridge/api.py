"""Small WSGI API using raw uploads (no unbounded multipart parser)."""
import hmac
import json
import os
import secrets
import signal
import subprocess
import sys
import tempfile
from http import HTTPStatus
from pathlib import Path
from urllib.parse import parse_qs

MAX_UPLOAD = 20 * 1024 * 1024
MAX_OUTPUT = 40 * 1024 * 1024
FORMATS = {'txt': ['pdf', 'docx'], 'docx': ['pdf', 'txt'],
           'pdf': ['txt', 'docx', 'png'], 'jpg': ['pdf', 'txt', 'docx'],
           'jpeg': ['pdf', 'txt', 'docx'], 'png': ['pdf', 'txt', 'docx']}
MIME = {'pdf': 'application/pdf', 'txt': 'text/plain; charset=utf-8',
        'docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        'zip': 'application/zip'}


def reply(start, status, data, headers=()):
    body = json.dumps(data).encode()
    start(f'{status} {HTTPStatus(status).phrase}', [('Content-Type', 'application/json'),
          ('Content-Length', str(len(body))), ('Cache-Control', 'no-store'),
          ('X-Content-Type-Options', 'nosniff'), *headers])
    return [body]


def stop_process(process):
    if os.name == 'posix':
        try:
            os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    elif process.poll() is None:
        process.kill()
    process.wait()


def run_job(work):
    env = {k: v for k, v in os.environ.items() if k in
           ('PATH', 'SYSTEMROOT', 'WINDIR', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'DOCBRIDGE_FONT')}
    env.update(HOME=str(work), TMPDIR=str(work), TEMP=str(work), TMP=str(work),
               OMP_THREAD_LIMIT='1', LANG='C.UTF-8', PYTHONDONTWRITEBYTECODE='1')
    process = subprocess.Popen([sys.executable, '-m', 'docbridge.worker', str(work)],
                               env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               close_fds=True, start_new_session=(os.name == 'posix'))
    try:
        process.wait(timeout=180)
    except subprocess.TimeoutExpired:
        return {'ok': False, 'timeout': True, 'error': 'Conversion exceeded 180 seconds.'}
    finally:
        # Also remove any LibreOffice/Tesseract descendants left after an error.
        stop_process(process)
    response = work / 'response.json'
    if process.returncode != 0 or not response.is_file() or response.stat().st_size > 65536:
        return {'ok': False, 'error': 'Conversion worker failed or exceeded resource limits.'}
    return json.loads(response.read_text(encoding='utf-8'))


def application(environ, start_response):
    path = environ.get('PATH_INFO', '/')
    method = environ.get('REQUEST_METHOD', 'GET')
    if path == '/healthz' and method == 'GET':
        return reply(start_response, 200, {'status': 'ok', 'service': 'DocBridge'})
    key = os.getenv('DOCBRIDGE_API_KEY', '')
    if len(key) < 32 or key.startswith('replace-'):
        return reply(start_response, 503, {'error': 'Configure a strong API key before using this service.'})
    supplied = environ.get('HTTP_AUTHORIZATION', '')
    if not hmac.compare_digest(supplied.encode(), ('Bearer ' + key).encode()):
        return reply(start_response, 401, {'error': 'Valid Bearer API key required.'},
                     [('WWW-Authenticate', 'Bearer')])
    if path == '/v1/formats' and method == 'GET':
        return reply(start_response, 200, {'formats': FORMATS, 'max_upload_bytes': MAX_UPLOAD,
                     'max_pages': 50, 'languages': ['eng', 'rus', 'eng+rus'],
                     'ocr_modes': ['auto', 'always', 'never'], 'png_output': 'ZIP of page PNGs'})
    if path != '/v1/convert':
        return reply(start_response, 404, {'error': 'Endpoint not found.'})
    if method != 'POST':
        return reply(start_response, 405, {'error': 'Use POST.'}, [('Allow', 'POST')])
    if environ.get('HTTP_TRANSFER_ENCODING'):
        return reply(start_response, 411, {'error': 'Send a fixed Content-Length, not chunked encoding.'})
    try:
        length = int(environ.get('CONTENT_LENGTH', ''))
    except ValueError:
        return reply(start_response, 411, {'error': 'Content-Length is required.'})
    if not 0 < length <= MAX_UPLOAD:
        return reply(start_response, 413, {'error': 'Upload must contain 1 byte to 20 MiB.'})
    if environ.get('CONTENT_TYPE', '').split(';')[0].strip() != 'application/octet-stream':
        return reply(start_response, 415, {'error': 'Send raw file bytes as application/octet-stream.'})
    try:
        params = parse_qs(environ.get('QUERY_STRING', ''), keep_blank_values=True, max_num_fields=4)
        if any(k not in ('source', 'target', 'language', 'ocr') or len(v) != 1 for k, v in params.items()):
            raise ValueError()
        source = params.get('source', [''])[0]
        target = params.get('target', [''])[0]
        language = params.get('language', ['eng'])[0]
        mode = params.get('ocr', ['auto'])[0]
        if (target not in FORMATS.get(source, []) or language not in ('eng', 'rus', 'eng+rus')
                or mode not in ('auto', 'always', 'never')):
            raise ValueError()
    except ValueError:
        return reply(start_response, 400, {'error': 'Invalid conversion options. See GET /v1/formats.'})
    request_id = secrets.token_hex(8)
    try:
        with tempfile.TemporaryDirectory(prefix='docbridge-') as folder:
            work = Path(folder)
            with (work / ('input.' + source)).open('wb') as dest:
                remaining = length
                while remaining:
                    chunk = environ['wsgi.input'].read(min(65536, remaining))
                    if not chunk:
                        return reply(start_response, 400, {'error': 'Incomplete upload.'})
                    dest.write(chunk)
                    remaining -= len(chunk)
            (work / 'request.json').write_text(json.dumps(dict(source=source, target=target,
                                                              language=language, mode=mode)))
            result = run_job(work)
            if not result.get('ok'):
                return reply(start_response, 504 if result.get('timeout') else 422,
                             {'error': result['error'], 'request_id': request_id})
            expected = 'result.zip' if target == 'png' else 'result.' + target
            if result.get('filename') != expected:
                raise ValueError('Invalid worker output')
            output = work / expected
            if not output.is_file() or output.stat().st_size > MAX_OUTPUT:
                raise ValueError('Invalid output size')
            body = output.read_bytes()
            headers = [('Content-Type', MIME[output.suffix[1:]]), ('Content-Length', str(len(body))),
                       ('Content-Disposition', 'attachment; filename="' + expected + '"'),
                       ('Cache-Control', 'no-store'), ('X-Content-Type-Options', 'nosniff'),
                       ('X-Request-ID', request_id), ('X-OCR-Pages', str(result['ocr_pages']))]
            if result['warnings']:
                headers.append(('X-Conversion-Warnings', ' '.join(result['warnings'])))
        # The temporary input, outputs, OCR images and office profile are deleted before returning.
        start_response('200 OK', headers)
        return [body]
    except Exception:
        return reply(start_response, 500, {'error': 'Conversion failed.', 'request_id': request_id})
