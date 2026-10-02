# DocBridge

Self-hosted document conversion and OCR API for your website. Install it on a Linux VPS with Docker Compose, then send a file from your website's backend and receive the converted file in the HTTP response. Processing happens on your server, without a third-party document API or paid AI key.

## Supported conversions

| Input | Output | Notes |
| --- | --- | --- |
| UTF-8 TXT | PDF, DOCX | Creates a new document with simple formatting |
| DOCX | PDF | LibreOffice conversion; fonts and complex layouts may differ |
| DOCX | TXT | Body paragraphs and tables, in document order |
| PDF | TXT, DOCX | Extracts existing text; OCR for pages with no text layer |
| PDF | PNG | Returns a ZIP containing one image per page |
| JPG, JPEG, PNG | PDF | Fits one image on an A4 page, without adding OCR text |
| JPG, JPEG, PNG | TXT, DOCX | Tesseract OCR, English and/or Russian |

This is a defined set of formats, not a universal converter. Legacy DOC, spreadsheets, presentations, archives, animated images, encrypted PDFs, and arbitrary file types are not supported. PDF/image to DOCX produces editable text, not an exact reconstruction of tables or page layout. Handwriting and poor scans may be inaccurate. OCR output should be reviewed.

## Quick start on a VPS

Use a Linux x86-64 or ARM64 VPS with Docker Engine and the Compose plugin. Start with 2 CPU cores, 4 GB of RAM, and several GB of free disk space. The service is limited to 2 GB of RAM and two workers. See [Docker's official installation guide](https://docs.docker.com/engine/install/).

```sh
git clone https://github.com/devmeto5/docbridge.git
cd docbridge
sh setup.sh
curl http://127.0.0.1:8080/healthz
```

Or download the repository using **Code > Download ZIP**, extract it, enter the extracted folder, and run `sh setup.sh`. The script generates a random API key in `.env` on its first run and starts the service. Keep `.env` private. It is excluded from Git and Docker build context.

The first build downloads LibreOffice, Tesseract and language data. Subsequent starts are faster. The API listens on **127.0.0.1:8080** on your VPS; it is not automatically exposed to the internet. Run your website backend on the same server, or configure HTTPS through a reverse proxy. A normal shared PHP hosting account without Docker cannot run the conversion engine itself, but its PHP backend can call a separate VPS running DocBridge.

## First conversion

In the project directory, load the generated key and send a UTF-8 text file:

```sh
set -a
. ./.env
set +a
printf 'Hello from DocBridge!\n' > example.txt
curl --fail-with-body --max-time 200 \
  -H "Authorization: Bearer $DOCBRIDGE_API_KEY" \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @example.txt \
  'http://127.0.0.1:8080/v1/convert?source=txt&target=pdf' \
  --output result.pdf
```

For OCR of a scanned PDF:

```sh
curl --fail-with-body --max-time 200 \
  -H "Authorization: Bearer $DOCBRIDGE_API_KEY" \
  -H 'Content-Type: application/octet-stream' \
  --data-binary @scan.pdf \
  'http://127.0.0.1:8080/v1/convert?source=pdf&target=docx&language=eng%2Brus&ocr=auto' \
  --output result.docx
```

Encode the plus sign as `%2B` in query strings. Upload raw file bytes, not multipart/form-data. Requests must include a fixed Content-Length; curl with `--data-binary @file` handles this automatically. Uploaded filenames are never used as server paths.

## API

All endpoints except `/healthz` require `Authorization: Bearer YOUR_API_KEY`.

| Endpoint | Purpose |
| --- | --- |
| `GET /healthz` | Process liveness; does not test the conversion engines |
| `GET /v1/formats` | Supported formats, OCR languages and limits |
| `POST /v1/convert` | Raw upload and synchronous conversion |

Conversion query parameters:

| Parameter | Values |
| --- | --- |
| `source` | `txt`, `docx`, `pdf`, `jpg`, `jpeg`, `png` |
| `target` | A supported output for that source; see the table above |
| `language` | `eng` (default), `rus`, `eng+rus` |
| `ocr` | `auto` (default), `always`, `never` |

`auto` uses existing PDF text and OCRs pages with no extracted text. A page containing both digital text and a scanned region may need `always` to capture the scanned region too. `never` skips OCR and may return blank text for scans; image-to-text requests with `never` are rejected. OCR options do not add a searchable text layer when converting an image to PDF.

Successful conversion returns the file as an attachment. `X-OCR-Pages` reports the number of pages sent to OCR. `X-Conversion-Warnings`, when present, describes conversion limitations. `X-Request-ID` identifies the request. No document content is written to application logs.

Errors return JSON: `400` invalid options/upload, `401` invalid key, `411` missing Content-Length, `413` oversized/empty upload, `415` wrong Content-Type, `422` conversion failure or unsupported document content, `503` API key not configured, `504` conversion deadline exceeded, or `500` an internal failure. Check the HTTP status before treating the response as a file.

## Website integration

Your website backend accepts the user's upload, checks that user's permissions and quota, and calls DocBridge. It then returns the converted file to the user. Keep the API key on the backend: do not put it in browser JavaScript, public HTML, or a mobile app. DocBridge deliberately does not enable browser CORS access.

- [PHP integration function](examples/convert.php) for PHP 8 with cURL.
- [Node.js integration function](examples/convert.mjs) using built-in fetch.
- [Nginx HTTPS proxy example](deploy/nginx.conf.example) if the backend is on a different host.

The examples provide a backend conversion function, not a public upload page or user account system. Enforce your website's authentication, CSRF protection, upload quotas and rate limits before calling this service. It uses one shared service API key and has no per-user billing, accounts, job history, or queue dashboard.

## Limits and isolation

- Maximum upload: 20 MiB; output: 40 MiB; PDF: 50 pages; raster: 25 megapixels; extracted text: one million characters.
- DOCX archives are checked before conversion: 80 MiB unpacked, at most 5,000 entries. Embedded objects, macros, external relationships (including external hyperlinks), external fields and XML document types are rejected. Remove links or flatten unsupported content first.
- Each conversion runs in a separate process, with a 180-second deadline. On Linux a seccomp filter blocks creation of network sockets by that worker and its child processes, while permitting local Unix sockets. The worker does not receive the API key.
- Docker runs as a non-root user with a read-only filesystem, dropped capabilities, a process limit, and a 512 MiB temporary filesystem. CPU and output-file limits apply to workers.
- Inputs, intermediate files and results are removed from the temporary directory before the response is returned. A worker forcibly killed by the server/container can leave files in tmpfs until the container restarts. No persistent document storage volume is mounted. This is not a guarantee of forensic erasure; server swap and crash handling are controlled by the operator.
- English/Russian fonts and OCR models are included. Other scripts require appropriate fonts and language models; complex typesetting is not guaranteed.

The container is a baseline isolation boundary, not a security audit or a replacement for keeping parsers and the operating system updated. Use a dedicated service/VPS for untrusted public uploads. Review dependency updates regularly and rerun tests before deploying them.

## Operations

```sh
docker compose ps
docker compose logs --tail=100
docker compose down
# After reviewing upstream changes:
git pull --ff-only
docker compose up -d --build
```

To rotate the key, replace `DOCBRIDGE_API_KEY` in `.env` with a new random value, update your website backend, and run `docker compose up -d`. Never commit `.env`. For production access from another server, use HTTPS and firewall restrictions. The included Nginx example sets request limits and timeouts; certificate provisioning is up to your hosting setup.

## Tests

The GitHub Actions workflow builds the Docker image, tests actual PDF/DOCX conversion and image/scanned-PDF OCR, checks worker network isolation, and exercises the live HTTP endpoint under Compose. The run must be green before treating a revision as verified.

```sh
docker build -t docbridge:test .
docker run --rm --read-only --cap-drop ALL --security-opt no-new-privileges \
  --memory 2g --cpus 2 --pids-limit 128 --tmpfs /tmp:size=512m,mode=1777 \
  -e REQUIRE_ENGINES=1 docbridge:test python -m unittest discover -s tests -v
```

Without `REQUIRE_ENGINES=1`, local tests skip LibreOffice/Tesseract cases when those tools are absent. A passing partial local test run does not verify OCR or the Docker deployment.

## Components

Uses LibreOffice for DOCX-to-PDF, Tesseract for OCR, PDFium for page rendering, pypdf for PDF text extraction, ReportLab for PDF creation, and python-docx for editable text documents. Each dependency retains its own license. There is no third-party document-processing API.

Documentation: [Tesseract](https://tesseract-ocr.github.io/tessdoc/), [LibreOffice command-line parameters](https://help.libreoffice.org/latest/en-US/text/shared/guide/start_parameters.html), [Docker Compose](https://docs.docker.com/compose/).
