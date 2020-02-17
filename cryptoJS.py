from os import urandom
from hashlib import md5
from base64 import b64encode, b64decode

import pyaes

def bytes_to_key(data, salt, output=48):
    assert len(salt) == 8, len(salt)
    data += salt
    key = md5(data).digest()
    final_key = key
    while len(final_key) < output:
        key = md5(key + data).digest()
        final_key += key
    return final_key[:output]

def encrypt(message, passphrase):
    salt = urandom(8)

    key_iv = bytes_to_key(passphrase, salt, 32+16)
    key = key_iv[:32]
    iv = key_iv[32:]

    encrypter   = pyaes.Encrypter(pyaes.AESModeOfOperationCBC(key, iv))
    ciphertext  = encrypter.feed(message)
    ciphertext += encrypter.feed()

    return b64encode(b"Salted__" + salt + ciphertext)

def decrypt(encrypted, passphrase):
    encrypted = b64decode(encrypted)
    assert encrypted[0:8] == b"Salted__"

    salt = encrypted[8:16]
    key_iv = bytes_to_key(passphrase, salt, 32+16)
    key = key_iv[:32]
    iv = key_iv[32:]

    decrypter  = pyaes.Decrypter(pyaes.AESModeOfOperationCBC(key, iv))
    decrypted  = decrypter.feed(encrypted[16:])
    decrypted += decrypter.feed()

    return decrypted