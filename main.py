import socket
import string, random
import json
import os

# TODO: stop using these!
from colorama import init
from colorama import Fore, Back, Style

# Initialize colorama.
init(autoreset=True)

token_array = None

# Config
config = open('config.ini', 'r')
config_contents = config.read().split("\n")
for line in config_contents:
    line = line.split("=")
    if line[0].strip() == "TOKEN": # TEMP! Token array.
        token_array = line[1].strip()
    else: # Config value is unknown. continue iterating anyways.
        continue

if token_array is None:
    print("No tokens found.")
    os.exit()

# Host IP. Blank string = localhost
SOCKET_LOCATION = "/tmp/tohru.sock"

# Remove socket so we can re-use.
if os.path.exists(SOCKET_LOCATION):
    os.remove(SOCKET_LOCATION)

sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)

# Maximum amount of data we will accept.
MAX_PACKET = 1024000 # 1024MB

# Array of supported filetypes.
UNSUPPORTED_FILETYPES = ["virus"] # xd

# Length of randomly generated filenames.
FILENAME_LENGTH = 12

# Location to save uploads to.
SAVE_LOCATION   = "/home/cmyui/uploads/"

# Generate a random FILENAME_LENGTH string.
def generate_filename(length=FILENAME_LENGTH): # Generate using all lowercase, uppercase, and digits.
    return "".join(random.choice(string.ascii_letters + string.digits) for i in range(length))


def handle_request(data):
    # Split the data into headers, content headers, and body.
    split = data.split(b"\r\n\r\n")
    # Assign the headers and content headers from split[0] and split[1].
    headers, content_headers = split[0].decode().split("\r\n"), split[1].decode().split("\r\n")
    # Assign body from split[2].
    body = split[2]

    # Set request values to None.
    request_IP, request_UAgent, request_token = [None] * 3

    # Iterate through content headers to assign keys and values.
    for header in headers:
        # Split up the header into keys and values.
        current_header = header.split(": ")

        # Check if the header has been properly split into key and value.
        if len(current_header) > 1:
            # Assign the key and value for the header.
            header_key, header_value = current_header

            # Check if the header is the CF-Connecting-IP header.
            # This header is the user's IP address, passed through cloudflare to us.
            if header_key == "CF-Connecting-IP":
                request_IP = header_value

            # Check if the header is the token header.
            # This is the token used in the user's ShareX config, for toh.ru.
            elif header_key == "token":
                request_token = header_value

            # Check if the header is the User-Agent header.
            # This header essentially shows what application the request was sent from.
            # Since toh.ru only allows for ShareX to be used for uploads, that is what we check for.
            elif header_key == "User-Agent":
                request_UAgent = header_value

    # The user provided a token that is not in our accepted token array.
    if not request_token in token_array:
        print(Fore.RED + f"Invalid HTTP Header (token): {request_token}")
        return False

    # Only submit ShareX for the time being.
    if not request_UAgent.startswith("ShareX"):
        print(Fore.RED + f"Invalid HTTP Header (User-Agent): {request_UAgent}")
        return

    # Content headers include Content-Type and Content-Disposition.
    request_ContentDisposition, request_ContentType, extension_type = [None] * 3

    # Iterate through content headers to assign keys and values.
    for header in content_headers:
        # Split up the header into keys and values.
        current_header = header.split(": ")

        # Check if the header has been properly split into key and value.
        if len(current_header) > 1:
            # Assign the key and value for the header.
            header_key, header_value = current_header

            # Check if the header is the Content-Disposition header.
            # This header is made up of three segments; two of which (1, 2) are useful for us.
            # Index 1: name="files". If it is not this, they have an incorrect sharex config.
            # Index 2: This index contains the filename they are uploading, and more importantly, the extension.
            if header_key == "Content-Disposition":
                cd = header_value.split("; ")
                if len(cd) == 3:
                    if cd[1] != 'name="files[]"':
                        return False # They did not send files[]?
                    extension_type = cd[2].split(".")[-1].replace('"', "")
                else:
                    return False # User sent an invalid Content-Disposition header.

            # Check if the header is the Content-Type header.
            # At the moment, we only check that this header exists.
            elif header_key == "Content-Type":
                request_ContentType = header_value

    # Extension type is not allowed.
    if extension_type in UNSUPPORTED_FILETYPES:
        return False

    # One of the required headers was not recieved.
    if request_ContentType is None or request_IP is None or request_UAgent is None or request_token is None:
        print(Fore.RED + "A required header was not recieved.")
        return False

    # Passed checks! Generate filename and save the png/serve the filename back.
    filename = generate_filename()

    # Write to file
    f = open(f'{SAVE_LOCATION}{filename}.{extension_type}', 'wb+')
    f.write(body)
    f.close()

    print(Fore.GREEN + f"{request_IP} - Request successfully processed. File: {SAVE_LOCATION}{filename}.{extension_type}\n")
    return f"{filename}.{extension_type}" # Return filename to be sent back


# Initialize our socket and begin the listener.
print(f"\nBooting up tohru.")
sock.bind(SOCKET_LOCATION)
os.chmod(SOCKET_LOCATION, 0o777)
sock.listen(2) # param = queued connections.
print("Waiting for requests..\n")

# Iterate through connections indefinitely.
while True:
    conn, addr = sock.accept()
    with conn:
        while True:
            data = conn.recv(MAX_PACKET)
            # TODO: get all the data u retard lol
            #data += conn.recv(MAX_PACKET)
            #data += conn.recv(MAX_PACKET)
            #data += conn.recv(MAX_PACKET)
            # User is accessing from the html page.
            if len(data) < 800:
                conn.send(b"No?")
                conn.close()
                break

            file = handle_request(data)
            if not file: # Request parse failed.
                conn.send(b"HTTP/1.1 400 Bad Request")
                conn.send(b"\n")
                conn.send(b'Bad request, incorrect parameters.')
                conn.close()
                break

            # We've successfully saved the image and all data was correct. Prepare to send back 200.

            _response_body = { # Define this above headers for Content-Length header
                "success": "true",
                "files": [
                    {
                        "name": file,
                        "size":"4",
                        "url":"https://toh.ru/uploads/" + file
                    }]
                }

            response_body = json.dumps(_response_body)

            response_headers = {
                'Content-Type': 'text/html; encoding=utf-8',
                'Content-Length': len(file) + len(response_body),
                'Connection': 'close',
            }

            response_headers_raw = "".join("%s: %s\n" % (k, v) for k, v in response_headers.items())

            # Status
            conn.send(b"HTTP/1.1 200 OK")

            # Headers
            conn.send(response_headers_raw.encode())

            # New line to separate body
            conn.send(b"\n")

            conn.send(response_body.encode())
            conn.close()
            break