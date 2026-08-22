import urllib.request
import zipfile
import ssl
import os

print("Downloading deno...")
ctx = ssl.create_default_context()
ctx.check_hostname = False
ctx.verify_mode = ssl.CERT_NONE

urllib.request.urlretrieve(
    "https://github.com/denoland/deno/releases/latest/download/deno-x86_64-pc-windows-msvc.zip",
    "deno.zip"
)

print("Extracting...")
with zipfile.ZipFile("deno.zip", 'r') as zip_ref:
    zip_ref.extractall(".")

os.remove("deno.zip")
print("Done! deno.exe is ready.")
