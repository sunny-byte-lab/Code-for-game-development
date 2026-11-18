"""N.E.X.U.S. Secure Protocol Server.
Runs an asynchronous TCP JSON protocol server in a daemon thread.
Uses standard library asyncio with zero external dependencies.
"""

import json
import logging
import asyncio
import threading
from typing import Optional, Callable, Dict, Any, Tuple

from nexus_protocol.spec import ProtocolMessage, MessageType, CommandAction
from nexus_protocol.security import SecurityManager
from nexus_protocol.validator import CommandValidator

logger = logging.getLogger("NEXUS.Protocol.Server")


class RemoteProtocolServer:
    """Async background server for receiving authenticated mobile commands."""

    def __init__(self,
                 host: str = "127.0.0.1",
                 port: int = 8765,
                 command_dispatcher: Optional[Callable[[CommandAction, Dict[str, Any]], Tuple[bool, str]]] = None,
                 allowed_apps: Optional[set] = None):
        self.host = host
        self.port = port
        self.command_dispatcher = command_dispatcher
        self.security = SecurityManager()
        self.validator = CommandValidator(allowed_apps=allowed_apps)

        self._is_running = False
        self._thread: Optional[threading.Thread] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._server: Optional[asyncio.Server] = None
        self._clients: set = set()

    @property
    def is_running(self) -> bool:
        return self._is_running

    def start(self) -> bool:
        """Starts the protocol server in a background thread."""
        if self._is_running:
            return True

        self._is_running = True
        self._thread = threading.Thread(target=self._run_server_thread, daemon=True, name="NexusProtocolServer")
        self._thread.start()
        logger.info(f"Protocol Server starting on {self.host}:{self.port}...")
        return True

    def stop(self) -> None:
        """Stops the protocol server and revokes all active sessions."""
        if not self._is_running:
            return

        self._is_running = False
        self.security.revoke_all_sessions()

        if self._loop and self._loop.is_running():
            asyncio.run_coroutine_threadsafe(self._shutdown_async(), self._loop)

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.5)

        logger.info("Protocol Server stopped cleanly.")

    def _run_server_thread(self) -> None:
        """Entry point for background asyncio thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._listen_async())
        except Exception as e:
            logger.error(f"Error in protocol server loop: {e}")
        finally:
            self._loop.close()

    async def _listen_async(self) -> None:
        """Initializes TCP server listening loop."""
        try:
            self._server = await asyncio.start_server(self._handle_client, self.host, self.port)
            logger.info(f"N.E.X.U.S. Remote Control Protocol listening on {self.host}:{self.port}")
            async with self._server:
                await self._server.serve_forever()
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Failed to bind protocol server on {self.host}:{self.port}: {e}")
            self._is_running = False

    async def _shutdown_async(self) -> None:
        """Closes all client sockets and stops server."""
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        for writer in list(self._clients):
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
        self._clients.clear()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handles a connected mobile client connection."""
        self._clients.add(writer)
        client_addr = writer.get_extra_info("peername")
        logger.info(f"[CLIENT CONNECTED] {client_addr}")

        try:
            while self._is_running:
                line = await reader.readline()
                if not line:
                    break

                try:
                    raw_data = json.loads(line.decode("utf-8").strip())
                    msg = ProtocolMessage.from_dict(raw_data)
                except Exception as e:
                    await self._send_reply(writer, ProtocolMessage(
                        msg_type=MessageType.ERROR,
                        payload={"error": f"INVALID_JSON: {e}"}
                    ))
                    continue

                response = self._process_message(msg)
                if response:
                    await self._send_reply(writer, response)

        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        except Exception as e:
            logger.debug(f"Client communication error: {e}")
        finally:
            self._clients.discard(writer)
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.info(f"[CLIENT DISCONNECTED] {client_addr}")

    def _process_message(self, msg: ProtocolMessage) -> Optional[ProtocolMessage]:
        """Processes and routes an incoming ProtocolMessage."""
        if msg.msg_type == MessageType.HELLO:
            return ProtocolMessage(
                msg_type=MessageType.HELLO,
                payload={"server": "N.E.X.U.S. Neural OS", "version": "2.5.0", "pairing_required": True}
            )

        if msg.msg_type == MessageType.PAIR_REQUEST:
            pin = str(msg.payload.get("pin", ""))
            device_id = str(msg.payload.get("device_id", "unknown"))
            device_name = str(msg.payload.get("device_name", "Mobile Device"))

            ok, token, reason = self.security.verify_pin_and_create_session(pin, device_id, device_name)
            if ok:
                logger.info(f"[DEVICE PAIRED] {device_name} ({device_id}) successfully paired.")
                return ProtocolMessage(
                    msg_type=MessageType.AUTH_SUCCESS,
                    token=token,
                    payload={"device_id": device_id, "message": "PAIRED_AND_AUTHENTICATED"}
                )
            else:
                logger.warning(f"[PAIRING REJECTED] {device_name}: {reason}")
                return ProtocolMessage(
                    msg_type=MessageType.AUTH_FAILED,
                    payload={"error": reason}
                )

        if msg.msg_type == MessageType.HEARTBEAT:
            return ProtocolMessage(msg_type=MessageType.HEARTBEAT, payload={"status": "ALIVE"})

        # All commands and state updates require validated token, nonce, and freshness
        is_valid, session, err = self.security.validate_message(msg.token, msg.nonce, msg.timestamp)
        if not is_valid:
            return ProtocolMessage(
                msg_type=MessageType.AUTH_FAILED,
                payload={"error": err}
            )

        if msg.msg_type == MessageType.COMMAND:
            action_name = str(msg.payload.get("action", ""))
            cmd_payload = msg.payload.get("parameters", {})

            val_ok, action, clean_payload, val_err = self.validator.validate_command(action_name, cmd_payload)
            if not val_ok:
                logger.warning(f"[COMMAND REJECTED] {session.device_name}: {val_err}")
                return ProtocolMessage(
                    msg_type=MessageType.ERROR,
                    payload={"error": val_err, "action": action_name}
                )

            # Dispatch command to PC runtime
            if self.command_dispatcher:
                try:
                    success, res_msg = self.command_dispatcher(action, clean_payload)
                    return ProtocolMessage(
                        msg_type=MessageType.COMMAND_ACK,
                        payload={"action": action.value, "success": success, "message": res_msg}
                    )
                except Exception as e:
                    logger.error(f"Error executing command {action.value}: {e}")
                    return ProtocolMessage(
                        msg_type=MessageType.ERROR,
                        payload={"error": f"EXECUTION_FAILURE: {e}", "action": action.value}
                    )
            return ProtocolMessage(
                msg_type=MessageType.COMMAND_ACK,
                payload={"action": action.value, "success": True, "message": "SIMULATED_DISPATCH"}
            )

        if msg.msg_type == MessageType.DISCONNECT:
            if msg.token:
                self.security.revoke_session(msg.token)
            return ProtocolMessage(msg_type=MessageType.DISCONNECT, payload={"message": "SESSION_TERMINATED"})

        return None

    async def _send_reply(self, writer: asyncio.StreamWriter, msg: ProtocolMessage) -> None:
        """Sends a newline-delimited JSON message to the client socket."""
        try:
            line = (json.dumps(msg.to_dict()) + "\n").encode("utf-8")
            writer.write(line)
            await writer.drain()
        except Exception:
            pass
