import socket
import unittest
from unittest.mock import patch

from app import network


class RemoteUrlSafetyTests(unittest.TestCase):
    def test_loopback_and_embedded_credentials_are_rejected(self) -> None:
        with self.assertRaises(network.UnsafeRemoteUrl):
            network.ensure_public_http_url("http://127.0.0.1/private")
        with self.assertRaises(network.UnsafeRemoteUrl):
            network.ensure_public_http_url("https://user:pass@example.com/file")

    def test_dns_name_with_private_answer_is_rejected(self) -> None:
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.8", 0))]
        with patch.object(network.socket, "getaddrinfo", return_value=answer), self.assertRaises(
            network.UnsafeRemoteUrl
        ):
            network.ensure_public_http_url("https://cdn.example/file")

    def test_dns_name_with_public_answer_is_allowed(self) -> None:
        answer = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
        with patch.object(network.socket, "getaddrinfo", return_value=answer):
            network.ensure_public_http_url("https://cdn.example/file")


if __name__ == "__main__":
    unittest.main()
