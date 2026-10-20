"""Single-process live connections. No socket transport, database or upstream I/O."""
import asyncio
from dataclasses import dataclass, field
from uuid import UUID


@dataclass
class ViewerPeer:
    token: UUID
    viewer: dict
    queue: asyncio.Queue = field(default_factory=lambda: asyncio.Queue(maxsize=32))
    closing: bool = False

    def offer(self, message):
        if self.closing:
            return
        if self.queue.full():
            # Reconnect for a complete snapshot instead of silently losing updates.
            self.close(1013)
        else:
            self.queue.put_nowait(message)

    def close(self, code):
        self.closing = True
        while not self.queue.empty():
            self.queue.get_nowait()
        self.queue.put_nowait({'close': code})


class LiveViewers:
    def __init__(self):
        self.peers = {}

    def attach(self, token, viewer):
        if previous := self.peers.get(token):
            previous.close(4001)
        peer = ViewerPeer(token, viewer)
        self.peers[token] = peer
        return peer

    def detach(self, peer):
        if self.peers.get(peer.token) is peer:
            self.peers.pop(peer.token)

    def replace_profile(self, profile_id):
        for peer in self.peers.values():
            if peer.viewer['profile_id'] == profile_id:
                peer.close(4001)

    def update(self, token, viewer):
        if peer := self.peers.get(token):
            peer.viewer = viewer

    def active(self, bucket=None):
        return [peer for peer in self.peers.values() if not peer.closing and
                (bucket is None or self.bucket(peer.viewer) == bucket)]

    @staticmethod
    def bucket(viewer):
        state = viewer['state']
        return f"{state['team']}:{state['fan_style']}"
