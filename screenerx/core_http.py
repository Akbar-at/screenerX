"""Local/private HTTP adapter; production authentication belongs to the Worker."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlsplit

from .core import VERSION
from .engine import InputError


def make_handler(service,universe,allow_live=False):
    class Handler(BaseHTTPRequestHandler):
        def send_json(self,status,payload):
            encoded=json.dumps(payload,allow_nan=False).encode('utf-8')
            self.send_response(status); self.send_header('Content-Type','application/json; charset=utf-8')
            self.send_header('Content-Length',str(len(encoded))); self.end_headers(); self.wfile.write(encoded)

        def do_GET(self):
            request=urlsplit(self.path)
            try:
                if request.path=='/health': return self.send_json(200,{'status':'ok','engine_version':VERSION})
                if request.path in ('/v1/top10','/v1/coverage'):
                    report=service.screen(universe)
                    if request.path=='/v1/top10':
                        return self.send_json(200,{key:value for key,value in report.items() if key!='companies'})
                    return self.send_json(200,{key:value for key,value in report.items() if key!='top10'})
                if request.path.startswith('/v1/tickers/'):
                    ticker=unquote(request.path[len('/v1/tickers/'):])
                    live=parse_qs(request.query).get('live',['false'])[0]=='true'
                    if live and not allow_live: return self.send_json(403,{'error':'Live lookup disabled; inspect saved evidence or enable live explicitly'})
                    report=service.lookup(ticker,live)
                    return self.send_json(200,report)
                self.send_json(404,{'error':'Unknown route'})
            except (InputError,ValueError,KeyError) as exc: self.send_json(400,{'error':str(exc)})
            except Exception: self.send_json(500,{'error':'Core operation failed; inspect server logs'})
    return Handler


def serve(service,universe,host='127.0.0.1',port=8000,allow_live=False):
    server=ThreadingHTTPServer((host,port),make_handler(service,universe,allow_live))
    print(f'Core API: http://{host}:{server.server_port}; saved lookup and coverage-qualified top10',flush=True)
    try: server.serve_forever()
    except KeyboardInterrupt: pass
    finally: server.server_close()
