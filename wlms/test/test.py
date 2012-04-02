from collections import defaultdict

from twisted.internet import task
from twisted.internet.protocol import connectionDone
from twisted.test import proto_helpers
from twisted.trial import unittest

from wlms import MetaServer
from wlms.protocol import GamePingFactory, NETCMD_METASERVER_PING
from wlms.utils import make_packet
from wlms.db.flatfile import FlatFileDatabase

import logging
logging.basicConfig(level=logging.CRITICAL)

# Helper classes  {{{
class ClientStringTransport(proto_helpers.StringTransportWithDisconnection):
    def __init__(self, ip):
        self.client = [ip]
        proto_helpers.StringTransportWithDisconnection.__init__(self)

class _Base(object):
    def setUp(self):
        db = FlatFileDatabase("SirVer\t123456\tSUPERUSER\n" + "otto\tottoiscool\tREGISTERED\n")
        self.ms = MetaServer(db)
        self.clock = task.Clock()
        self._cons = [ self.ms.buildProtocol(None) for i in range(10) ]
        self._trs = [ ClientStringTransport("192.168.0.%i" % i) for i in range(10) ]
        self._gptr = None
        self._gpc = None

        self._packets = defaultdict(list)

        def create_game_pinger(gc, timeout):
            self._gpfac = GamePingFactory(gc, timeout)
            p = self._gpfac.buildProtocol(None)
            tr = ClientStringTransport("GamePinger")
            p.makeConnection(tr)
            self._gptr = tr
            self._gpc = p

        for c,tr in zip(self._cons, self._trs):
            c.callLater = self.clock.callLater
            c.seconds = self.clock.seconds
            c.create_game_pinger = create_game_pinger
            tr.protocol = c
            c.makeConnection(tr)

    def tearDown(self):
        for idx,c in enumerate(self._cons):
            self._recv(idx)
            self.assertFalse(len(self._packets[idx]), "There are still packets for %i: %r" % (idx, self._packets[idx]))
        for c in self._cons:
            c.transport.loseConnection()

    def discard_packets(self, for_whom):
        if isinstance(for_whom, int):
            for_whom = [for_whom]

        for client in for_whom:
            self._recv(client)
            self._packets[client] = []

    def expect(self, for_whom, what):
        if isinstance(for_whom, int):
            for_whom = [for_whom]

        for client in for_whom:
            self._recv(client)
            self.assertTrue(len(self._packets[client]), "Expected a packet for %i, but none was there" % client)

        packs = [ self._packets[client].pop(0) for client in for_whom ]

        for c,p in zip(for_whom, packs):
            self.assertEqual(what, p)

    def expect_nothing(self, for_whom):
        if isinstance(for_whom, int):
            for_whom = [for_whom]

        for client in for_whom:
            self._recv(client)
            self.assertTrue(len(self._packets[client])==0,
                    "There was a packet %i, but none was expected: %r" % (client, self._packets[client]))

    def _recv(self, client):
        d = self._trs[client].value()
        self._trs[client].clear()
        rv = []
        while len(d):
            size = (ord(d[0]) << 8) + ord(d[1])
            self.assertTrue(size <= len(d))
            rv.append(d[2:size][:-1].split("\x00"))
            d = d[size:]
        self.clock.advance(1e-5)
        self._packets[client].extend(rv)
        return rv

    def _send(self, client, *args, **kwargs):
        c = self._cons[client]
        c.dataReceived(make_packet(*args))
        self.clock.advance(1e-5)
# End: Helper classes  }}}

# Sending Basics  {{{
class TestBasics(_Base, unittest.TestCase):
    def test_sending_absolute_garbage_too_short(self):
        self._cons[0].dataReceived("\xff")
    def test_sending_absolute_garbage(self):
        self._cons[0].dataReceived("\xff\x37lkjdflsjflkjsf")
    def test_sending_nonexisting_packet(self):
        self._send(0, "BLUMBAQUATSCH")
        self.expect(0, ['ERROR', 'GARBAGE_RECEIVED', "INVALID_CMD"])
    def test_sending_toolittle_arguments_packet(self):
        self._send(0, "LOGIN", "hi")
        self.expect(0, ['ERROR', 'LOGIN', "Invalid integer: 'hi'"])

    def test_sendtwopacketsinone(self):
        self._send(0, "LOGIN", 0, "testuser", "build-17", "false")
        self.discard_packets(0)
        self._cons[0].dataReceived("\x00\x0aCLIENTS\x00"*2)
        self.expect(0, ['CLIENTS', '1', 'testuser', 'build-17', '', 'UNREGISTERED', ''])
        self.expect(0, ['CLIENTS', '1', 'testuser', 'build-17', '', 'UNREGISTERED', ''])

    def test_fragmented_packages(self):
        self._send(0, "LOGIN", 0, "testuser", "build-17", "false")
        self.discard_packets(0)

        self._cons[0].dataReceived("\x00\x0aCLI")
        self._cons[0].dataReceived("ENTS\x00\x00\x0a")
        self.expect(0, ['CLIENTS', '1', 'testuser', 'build-17', '', 'UNREGISTERED', ''])
        self._cons[0].dataReceived("CLIENTS\x00\x00\x08")
        self.expect(0, ['CLIENTS', '1', 'testuser', 'build-17', '', 'UNREGISTERED', ''])
# End: Sending Basics  }}}
# Test Regular Pinging {{{
class TestRegularPinging(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-17", "false")
        self.discard_packets(0)

    def test_regular_cycle(self):
        self.clock.advance(15) # Don't speak for 15 seconds
        self.expect(0, ["PING"])
        self._send(0, "PONG")

        self.clock.advance(15)
        self.expect(0,["PING"])
        self._send(0, "PONG")

    def test_stay_quiet(self):
        self.clock.advance(10.5)
        self.expect(0,["PING"])
        self.clock.advance(10.5)
        self.expect(0,["DISCONNECT", "CLIENT_TIMEOUT"])

    def test_delay_ping_by_regular_packet(self):
        self.clock.advance(9.9)
        self._send(0, "CHAT", "hello there", "")
        self.expect(0,["CHAT", 'bert', 'hello there', 'public'])

        self.clock.advance(9.9)
        self._send(0, "CHAT", "hello there", "")
        self.expect(0,["CHAT", 'bert', 'hello there', 'public'])

        self.clock.advance(10.1)
        self.expect(0,["PING"])
# End: Test Regular Pinging }}}

# Test Login  {{{
class TestLogin(_Base, unittest.TestCase):
    def test_loginanon(self):
        self._send(0, "LOGIN", 0, "testuser", "build-17", "false")
        self.expect(0, ['LOGIN', 'testuser', "UNREGISTERED"])
        self.expect(0, ['TIME', '0'])
        self.expect(0, ['CLIENTS_UPDATE'])

    def test_loginanon_unknown_protocol(self):
        self._send(0, "LOGIN", 10, "testuser", "build-17", "false")
        self.expect(0,['ERROR', 'LOGIN', "UNSUPPORTED_PROTOCOL"])

    def test_loginanon_withknownusername(self):
        self._send(0, "LOGIN", 0, "SirVer", "build-17", "false")
        self.expect(0, ['LOGIN', 'SirVer1', "UNREGISTERED"])
        self.expect(0, ['TIME', '0'])
        self.expect(0, ['CLIENTS_UPDATE'])

    def test_loginanon_onewasalreadythere(self):
        # Login client 0
        self._send(0, "LOGIN", 0, "testuser", "build-17", "false")
        self.expect(0, ['LOGIN', 'testuser', "UNREGISTERED"])
        self.expect(0, ['TIME', '0'])
        self.expect(0, ['CLIENTS_UPDATE'])

        # Login client 1
        self._send(1, "LOGIN", 0, "testuser", "build-17", "false")
        # Note: Other username
        self.expect(1, ['LOGIN', 'testuser1', "UNREGISTERED"])
        self.expect(1, ['TIME', '0'])

        self.expect([0,1], ['CLIENTS_UPDATE'])

    def test_nonanon_login_correct_password(self):
        self._send(0, "LOGIN", 0, "SirVer", "build-17", 1, "123456")
        self.expect(0, ['LOGIN', 'SirVer', "SUPERUSER"])
        self.expect(0, ['TIME', '0'])
        self.expect(0, ['CLIENTS_UPDATE'])

    def test_nonanon_login_onewasalreadythere(self):
        # Login client 0
        self._send(0, "LOGIN", 0, "SirVer", "build-17", 1, "123456")
        self.discard_packets(0)

        # Login again
        self._send(1, "LOGIN", 0, "SirVer", "build-17", 1, "123456")
        self.expect(1, ['ERROR', 'LOGIN', 'ALREADY_LOGGED_IN'])

    def test_nonanon_login_twousers_password(self):
        self._send(0, "LOGIN", 0, "SirVer", "build-17", 1, "123456")
        self.expect(0, ['LOGIN', 'SirVer', "SUPERUSER"])
        self.expect(0, ['TIME', '0'])
        self.expect(0, ['CLIENTS_UPDATE'])

        self._send(1, "LOGIN", 0, "otto", "build-18", 1, "ottoiscool")
        self.expect(1, ['LOGIN', 'otto', "REGISTERED"])
        self.expect(1, ['TIME', '0'])

        self.expect([0,1], ['CLIENTS_UPDATE'])

    def test_nonanon_login_incorrect_password(self):
        self._send(0, "LOGIN", 0, "SirVer", "build-17", 1, "12345")
        self.expect(0, ['ERROR', 'LOGIN', 'WRONG_PASSWORD'])
# End: Test Login  }}}
# # Test Disconnect  {{{
# TODO
# class TestDisconnect(_Base, unittest.TestCase):
#     def setUp(self):
#         _Base.setUp(self)
#         self._send(0, "LOGIN", 0, "bert", "build-17", "false")
#         self._send(1, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
#         self._recv(0)
#         self._recv(2)

#     def test_regular_disconnect(self):
#         self._send(0, "DISCONNECT", "Gotta fly now!")

#         p1, = self._recv(0)
#         self.assertEqual(p1, ["CLIENT_TIMEOUT"])

# # End: Test Disconnect  }}}
# TestMotd  {{{
class TestMotd(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-17", "false")
        self._send(1, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self._send(2, "LOGIN", 0, "SirVer", "build-17", "true", "123456")
        self.discard_packets([0,1,2])

    def test_setting_motd(self):
        self._send(2, "MOTD", "Schnulz is cool!")
        self.expect([0,1,2],["CHAT", "", "Schnulz is cool!", "system"])

    def test_login_with_motd_set(self):
        self._send(2, "MOTD", "Schnulz is cool!")
        self.discard_packets([0,1,2])

        self._send(3, "LOGIN", 0, "fasel", "build-18", "false")
        self.expect(3, ['LOGIN', 'fasel', "UNREGISTERED"])
        self.expect(3, ['TIME', '0'])
        self.expect(3, ['CLIENTS_UPDATE'])
        self.expect(3, ["CHAT", "", "Schnulz is cool!", "system"])

        self.expect([0,1,2], ["CLIENTS_UPDATE"])

    def test_setting_motd_forbidden(self):
        self._send(1, "MOTD", "Schnulz is cool!")
        self._send(0, "MOTD", "Schnulz is cool!")

        self.expect([0,1],["ERROR", "MOTD", "DEFICIENT_PERMISSION"])
# End: TestMotd  }}}
# TestAnnouncement  {{{
class TestAnnouncement(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-17", "false")
        self._send(1, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self._send(2, "LOGIN", 0, "SirVer", "build-17", "true", "123456")
        self.discard_packets([0,1,2])

    def test_setting_announcement(self):
        self._send(2, "ANNOUNCEMENT", "Schnulz is cool!")

        self.expect([0,1,2],["CHAT", "", "Schnulz is cool!", "system"])

    def test_setting_announcement_forbidden(self):
        self._send(1, "ANNOUNCEMENT", "Schnulz is cool!")
        self._send(0, "ANNOUNCEMENT", "Schnulz is cool!")

        self.expect([0,1],["ERROR", "ANNOUNCEMENT", "DEFICIENT_PERMISSION"])
# # End: TestAnnouncement  }}}
# Test Relogin  {{{
class TestRelogin_Anon(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-17", "false")
        self._send(2, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self._send(3, "LOGIN", 0, "SirVer", "build-17", "true", "123456")
        self.discard_packets([0,2,3])

    def test_relogin_ping_and_reply(self):
        self._send(1, "RELOGIN", 0, "bert", "build-17", "false")
        self.expect(0,["PING"])

        self._send(0, "PONG")
        self.expect_nothing(0)

        self.expect(1, ["ERROR", "RELOGIN", "CONNECTION_STILL_ALIVE"])

    def test_relogin_ping_and_noreply(self):
        self._send(1, "RELOGIN", 0, "bert", "build-17", "false")
        self.expect(0,["PING"])

        self.clock.advance(6)

        # Connection was terminated for old user
        self.expect(0,["DISCONNECT", "CLIENT_TIMEOUT"])
        self.expect([2,3],["CLIENTS_UPDATE"])

        # Relogin accepted
        self.expect(1,["RELOGIN"])

    def test_relogin_notloggedin(self):
        self._send(1, "RELOGIN", 0, "iamnotbert", "build-17", "false")
        self.expect(1,["ERROR", "RELOGIN", "NOT_LOGGED_IN"])
        self.expect_nothing(0)

    def test_relogin_wronginformation_wrong_proto(self):
        self._send(1, "RELOGIN", 1, "bert", "build-17", "false")
        self.expect(1,["ERROR", "RELOGIN", "WRONG_INFORMATION"])
        self.expect_nothing(0)

    def test_relogin_wronginformation_wrong_buildid(self):
        self._send(1, "RELOGIN", 0, "bert", "uild-17", "false")
        self.expect(1,["ERROR", "RELOGIN", "WRONG_INFORMATION"])
        self.expect_nothing(0)
    def test_relogin_wronginformation_wrong_loggedin(self):
        self._send(1, "RELOGIN", 0, "bert", "build-17", "true")
        self.expect(1,["ERROR", "RELOGIN", "WRONG_INFORMATION"])
        self.expect_nothing(0)
    def test_relogin_wronginformation_wrong_loggedin_nonanon(self):
        self._send(1, "RELOGIN", 0, "otto", "build-17", "false")
        self.expect(1,["ERROR", "RELOGIN", "WRONG_INFORMATION"])
        self.expect_nothing(0)
    def test_relogin_wronginformation_wrong_passwordl(self):
        self._send(1, "RELOGIN", 0, "otto", "build-17", "true", "12345")
        self.expect(1,["ERROR", "RELOGIN", "WRONG_INFORMATION"])
        self.expect_nothing(0)

    def test_relogin_loggedin_allcorrect(self):
        self._send(1, "RELOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self.expect(2,["PING"])

        self.clock.advance(6)

        # Connection was terminated for old user
        self.expect(2,["DISCONNECT", "CLIENT_TIMEOUT"])
        self.expect([0,3],["CLIENTS_UPDATE"])

        # Relogin accepted
        self.expect(1,["RELOGIN"])

class TestReloginWhileInGame(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-17", "false")
        self._send(2, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self._send(2, "GAME_CONNECT", "my cool game")
        self._gpc.dataReceived(NETCMD_METASERVER_PING)
        self.discard_packets([0,2])

    def test_relogin_ping_and_noreply(self):
        self.clock.advance(15)
        self.expect([0,2],["PING"])
        self._send(2, "PONG")

        self.clock.advance(15)
        self.expect(2, ["CLIENTS_UPDATE"])
        self.expect(2, ["PING"])
        self._send(2, "PONG")

        # Connection was terminated for old user
        self.expect(0,["DISCONNECT", "CLIENT_TIMEOUT"])
        self._send(1, "RELOGIN", 0, "bert", "build-17", "false")

        # Relogin accepted
        self.expect(1,["RELOGIN"])
        self.expect(2,["CLIENTS_UPDATE"])

        self._send(1, "CLIENTS")
        self.expect(1,["CLIENTS", '2',
            "bert", "build-17", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "my cool game", "REGISTERED", "",
        ])
# # End: Test Relogin  }}}
# Test Chat  {{{
class TestChat(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-17", "false")
        self._send(1, "LOGIN", 0, "ernie", "build-17", "false")
        self.discard_packets([0,1])

    def test_public_chat(self):
        self._send(0, "CHAT", "hello there", "")
        self.expect([0,1],["CHAT", "bert", "hello there", "public"])

    def test_sanitize_public_chat(self):
        self._send(0, "CHAT", "hello <rt>there</rt>\nhow<rtdoyoudo", "")
        self.expect([0,1],["CHAT", "bert", "hello &lt;rt>there&lt;/rt>\nhow&lt;rtdoyoudo", "public"])

    def test_private_chat(self):
        self._send(0, "CHAT", "hello there", "ernie")
        self.expect_nothing(0)
        self.expect(1, ["CHAT", "bert", "hello there", "private"])

    def test_sanitize_private_chat(self):
        self._send(0, "CHAT", "hello <rt>there</rt>\nhow<rtdoyoudo", "ernie")
        self.expect_nothing(0)
        self.expect(1, ["CHAT", "bert", "hello &lt;rt>there&lt;/rt>\nhow&lt;rtdoyoudo", "private"])
# End: Test Chat  }}}

# Test Game Creation/Joining  {{{
class TestGameCreation(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-16", "false")
        self._send(1, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self._send(2, "LOGIN", 0, "SirVer", "build-18", "true", "123456")
        self.discard_packets([0,1,2])

    def test_create_game_and_ping_reply(self):
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self.expect([0,1,2], ["GAMES_UPDATE"])
        self.expect([0,1,2], ["CLIENTS_UPDATE"])

        self._send(1, "CLIENTS")
        self.expect(1, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

        data = self._gptr.value(); self._gptr.clear()
        self.assertEqual(data, NETCMD_METASERVER_PING)
        self._gpc.dataReceived(NETCMD_METASERVER_PING)

        self.expect(0, ["GAME_OPEN"])
        self.expect([0, 1,2], ["GAMES_UPDATE"])

        self._send(1, "CLIENTS")
        self.expect(1, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

    def test_create_game_no_connection_to_game(self):
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self.expect([0,1,2], ["GAMES_UPDATE"])
        self.expect([0,1,2], ["CLIENTS_UPDATE"])

        self._gpfac.clientConnectionFailed(None, None)
        self.expect(0, ["ERROR", "GAME_OPEN", "GAME_TIMEOUT"])
        self.expect([0,1,2], ["GAMES_UPDATE"])

        self._send(2, "CLIENTS")
        self._send(2, "GAMES")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])
        self.expect(2, ["GAMES", "1", "my cool game", "build-16", "false"])

    def test_create_game_twice_pre_ping(self):
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self.discard_packets([0,1,2])

        self._send(1, "GAME_OPEN", "my cool game", 12)
        self.expect(1, ["ERROR", "GAME_OPEN", "GAME_EXISTS"])

        data = self._gptr.value(); self._gptr.clear()
        self.assertEqual(data, NETCMD_METASERVER_PING)
        self._gpc.dataReceived(NETCMD_METASERVER_PING)

        self.discard_packets([0,1,2])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

    def test_create_game_twice_post_ping(self):
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self.discard_packets([0,1,2])

        data = self._gptr.value(); self._gptr.clear()
        self.assertEqual(data, NETCMD_METASERVER_PING)
        self._gpc.dataReceived(NETCMD_METASERVER_PING)
        self.discard_packets([0,1,2])

        self._send(1, "GAME_OPEN", "my cool game", 12)
        self.expect(1, ["ERROR", "GAME_OPEN", "GAME_EXISTS"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

    def test_create_game_and_no_first_ping_reply(self):
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self.expect([0,1,2], ["GAMES_UPDATE"])
        self.expect([0,1,2], ["CLIENTS_UPDATE"])

        self.clock.advance(6)
        self.expect(0, ["ERROR", "GAME_OPEN", "GAME_TIMEOUT"])
        self.expect([0,1,2], ["GAMES_UPDATE"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

        self._send(2, "GAMES")
        self.expect(2, ["GAMES", "1", "my cool game", "build-16", "false"])

    def test_create_game_and_no_second_ping_reply(self):
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self.expect([0,1,2], ["GAMES_UPDATE"])
        self.expect([0,1,2], ["CLIENTS_UPDATE"])

        data = self._gptr.value(); self._gptr.clear()
        self.assertEqual(data, NETCMD_METASERVER_PING)
        self._gpc.dataReceived(NETCMD_METASERVER_PING)
        self.expect(0, ["GAME_OPEN"])
        self.expect([0, 1,2], ["GAMES_UPDATE"])

        self.clock.advance(119)
        self.expect([0,1,2], ["PING"])
        for i in range(3): self._send(i, "PONG")

        data = self._gptr.value(); self._gptr.clear()
        self.assertEqual(data, '')

        self.clock.advance(2)
        data = self._gptr.value(); self._gptr.clear()
        self.assertEqual(data, NETCMD_METASERVER_PING)

        # Now, do not answer ping
        self.clock.advance(118)
        self.expect([0,1,2], ["PING"])
        for i in range(3): self._send(i, "PONG")

        self.clock.advance(3)

        self.expect([0,1,2], ["GAMES_UPDATE"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

        self._send(2, "GAMES")
        self.expect(2, ["GAMES", "0"])

    def test_join_game(self):
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self.discard_packets([0,1,2])

        self._send(1, "GAME_CONNECT", "my cool game")
        self.expect(1, ["GAME_CONNECT", "192.168.0.0"])
        self.expect([0,1,2], ["CLIENTS_UPDATE"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "my cool game", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

    def test_join_full_game(self):
        self._send(0, "GAME_OPEN", "my cool game", 1)
        self.discard_packets([0,1,2])

        self._send(1, "GAME_CONNECT", "my cool game")
        self.expect(1, ["ERROR", "GAME_CONNECT", "GAME_FULL"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

    def test_non_existing_Game(self):
        self._send(1, "GAME_CONNECT", "my cool game")
        self.expect(1, ["ERROR", "GAME_CONNECT", "NO_SUCH_GAME"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])
# # End: Test Game Creation/Joining  }}}
# Test Game Starting  {{{
class TestGameStarting(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-16", "false")
        self._send(1, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self._send(2, "LOGIN", 0, "SirVer", "build-18", "true", "123456")
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self._send(1, "GAME_CONNECT", "my cool game")
        self.discard_packets([0,1,2])

    def test_start_game_without_being_in_one(self):
        self._send(2, "GAME_START")
        self.expect(2, ["ERROR", "GARBAGE_RECEIVED", "INVALID_CMD"])
        self.expect([0,1], ["CLIENTS_UPDATE"])

    def test_start_game_not_host(self):
        self._send(1, "GAME_START")
        self.expect(1, ["ERROR", "GAME_START", "DEFICIENT_PERMISSION"])

    def test_start_game(self):
        self._send(0, "GAME_START")
        self.expect(0, ["GAME_START"])
        self.expect([0, 1,2], ["GAMES_UPDATE"])
# End: Game Starting  }}}
# Test Game Leaving  {{{
class TestGameLeaving(_Base, unittest.TestCase):
    def setUp(self):
        _Base.setUp(self)
        self._send(0, "LOGIN", 0, "bert", "build-16", "false")
        self._send(1, "LOGIN", 0, "otto", "build-17", "true", "ottoiscool")
        self._send(2, "LOGIN", 0, "SirVer", "build-18", "true", "123456")
        self._send(0, "GAME_OPEN", "my cool game", 8)
        self._send(1, "GAME_CONNECT", "my cool game")
        self.discard_packets([0,1,2])

    def test_leave_game_nothost(self):
        self._send(1, "GAME_DISCONNECT")
        self.expect([0,1,2], ["CLIENTS_UPDATE"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

    def test_leave_game_host(self):
        self._send(0, "GAME_DISCONNECT")
        self.expect([0,1,2], ["CLIENTS_UPDATE"])
        self.expect([0,1,2], ["GAMES_UPDATE"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "3",
            "bert", "build-16", "", "UNREGISTERED", "",
            "otto", "build-17", "my cool game", "REGISTERED", "",
            "SirVer", "build-18", "", "SUPERUSER", ""
        ])

    def test_leave_not_in_game(self):
        self._send(2, "GAME_DISCONNECT")
        self.expect(2, ["ERROR", "GARBAGE_RECEIVED", "INVALID_CMD"])
        self.expect([0,1], ["CLIENTS_UPDATE"])

        self._send(2, "CLIENTS")
        self.expect(2, ["CLIENTS", "2",
            "bert", "build-16", "my cool game", "UNREGISTERED", "",
            "otto", "build-17", "my cool game", "REGISTERED", "",
        ])
# End: Game Leaving  }}}



