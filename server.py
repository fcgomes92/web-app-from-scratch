import mimetypes
import os
import socket
import typing
from queue import Queue, Empty
from threading import Thread

from request import Request
from response import Response
from util import strike

HOST = '0.0.0.0'
PORT = 9000

SERVER_ROOT = os.path.abspath(os.path.dirname(__file__))


def serve_file(sock: socket.socket, path: str) -> None:
    """
    Given a socket and the relative path to a file (relative to
    SERVER_SOCK), send that file to the socket if it exists.  If the
    file doesn't exist, send a "404 Not Found" response.
    """

    # default path and file
    if path == "/":
        path = "/index.html"

    abspath = os.path.normpath(os.path.join(SERVER_ROOT, path.lstrip("/")))
    if not abspath.startswith(SERVER_ROOT):
        response = Response(status="404 Not Found", content="Not Found")
        response.send(sock)
        return

    try:
        with open(abspath, "rb") as f:
            # stat = os.fstat(f.fileno())
            content_type, encoding = mimetypes.guess_type(abspath)
            if content_type is None:
                content_type = "application/octet-stream"

            if encoding is not None:
                content_type += f"; charset={encoding}"

            response = Response(status="200 OK", body=f)
            response.headers.add('content-type', content_type)
            response.send(sock)

    except FileNotFoundError:
        response = Response(status="404 Not Found", content="Not Found")
        response.send(sock)
        return


def accept_connection(skt):
    client_sock, client_addr = skt.accept()
    print(f"=" * 80)
    print(f"Request from: {client_addr}")

    with client_sock:
        try:
            request = Request.from_socket(client_sock)
            print(request)
            response = Response(status="404 Not Found", content="Not Found")
            response.send(client_sock)
        except Exception as e:
            print(f"Failed to parse request: {e}")
            response = Response(status="400 Bad Request", content="Bad request")
            response.send(client_sock)

    print(f"=" * 80)


class HTTPWorker(Thread):
    def __init__(self, connection_queue: Queue) -> None:
        super().__init__(daemon=True)

        self.connection_queue = connection_queue
        self.running = False

    def stop(self) -> None:
        self.running = False

    def run(self) -> None:
        self.running = True
        while self.running:
            try:
                client_sock, client_addr = self.connection_queue.get(timeout=1)
            except Empty:
                continue

            try:
                self.handle_client(client_sock, client_addr)
            except Exception:
                print(f"Unhandled error: {e}")
                continue
            finally:
                self.connection_queue.task_done()

    def handle_client(self,
                      client_sock: socket.socket,
                      client_addr: typing.Tuple[str, int]) -> None:
        with client_sock:
            try:
                request = Request.from_socket(client_sock)
                print(f'\t[{request.method}] {request.path}')

                if "100-continue" in request.headers.get("expect", ""):
                    response = Response(status="100 Continue")
                    response.send(client_sock)

                try:
                    content_length = int(request.headers.get("content-length", "0"))
                except ValueError:
                    content_length = 0

                if content_length:
                    body = request.body.read(content_length)
                    print(f'\tRequest body: {body}')

                if request.method != "GET":
                    response = Response(status="405 Method not allowed",
                                        content="Method not allowed")
                    return

                serve_file(client_sock, request.path)
            except Exception as e:
                print(f"Failed to parse request: {e}")
                response = Response(status="400 Bad Request",
                                    content="Bad request")
                response.send(client_sock)


class HTTPServer(object):
    def __init__(self, host='127.0.0.1', port=9000, worker_count=16) -> None:
        self.host = host
        self.port = port
        self.worker_count = worker_count
        self.worker_backlog = worker_count * 8
        self.connection_queue = Queue(self.worker_backlog)

    def serve_forever(self) -> None:
        workers = []
        for _ in range(self.worker_count):
            worker = HTTPWorker(self.connection_queue)
            worker.start()
            workers.append(worker)

        with socket.socket() as server_sock:
            server_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server_sock.bind((self.host, self.port))
            server_sock.listen(0)

            print(strike())
            print(f"Listening on {self.host}:{self.port}...")
            print(strike())

            while True:
                try:
                    self.connection_queue.put(server_sock.accept())
                except KeyboardInterrupt:
                    print("\nBye bye :)")
                    break

        for worker in workers:
            worker.stop()

        for worker in workers:
            worker.join(timeout=30)


server = HTTPServer(host=HOST, port=PORT)
server.serve_forever()
