__all__ = ["cloud_request"]

import re
from typing import Optional, Any, Set, List
from collections import defaultdict
from scratchattach.utils.encoder import Encoding
from random import randint

def split_encoded_pairs(s: str) -> list[str]:
    parts = []
    current = []
    i = 0
    while i < len(s):
        pair = s[i:i+2]
        if pair == "89" and i % 2 == 0:
            # cut here
            parts.append(''.join(current))
            current = []
            i += 2
        else:
            current.append(s[i])
            i += 1
    # append remainder
    parts.append(''.join(current))
    return parts


class ResponseDecoder:
    def __init__(self):
        self.buffers: dict[str, dict[int, str]] = defaultdict(dict)

    def decode_chunk(
        self,
        packet: str,
        *,
        allowed_ids: Optional[Set[str]] = None
    ) -> Optional[Any]:
        if not packet or '.' not in packet:
            return None

        raw_body, raw_suffix = packet.rsplit('.', 1)
        body = raw_body[1:] if raw_body.startswith('-') else raw_body
        if not body:
            return None

        m_int = re.match(r"^([A-Za-z0-9]+?)(\d{3})1$", raw_suffix)
        m_fin = re.match(r"^([A-Za-z0-9]+?)(2222|3222)$", raw_suffix)

        if m_int:
            request_id, idx_s = m_int.group(1), m_int.group(2)
            idx = int(idx_s)
            if allowed_ids and request_id not in allowed_ids:
                return None

            # Clear buffer on first chunk (idx==0 or 1)
            if idx in (0,1):
                self.buffers[request_id].clear()

            self.buffers[request_id][idx] = body
            return None

        elif m_fin:
            request_id, validation = m_fin.group(1), m_fin.group(2)
            if allowed_ids and request_id not in allowed_ids:
                return None

            self.buffers[request_id][float('inf')] = body

            # Assemble in order: intermediate chunks ascending, then final chunk last
            parts = [self.buffers[request_id][i] for i in sorted(
                self.buffers[request_id].keys(), key=lambda x: (x == float('inf'), x)
            )]
            payload = ''.join(parts)

            del self.buffers[request_id]

            if validation == "2222":
                if payload.endswith('89'):
                    payload = payload[:-2]
                elems = split_encoded_pairs(payload) if '89' in payload else [payload]

                decoded = []
                for e in elems:
                    try:
                        decoded_part = Encoding.decode(e)
                        decoded.append(decoded_part)
                    except Exception as ex:
                        decoded.append(e)

                return decoded if len(decoded) > 1 else decoded[0]

            elif validation == "3222":
                return payload

        else:
            return None


decoder = ResponseDecoder()

# SENDER

def generate_request_packets(
    request_name: str,
    args: List[str] = [],
    request_id: str = str(randint(10001,99999)),
    length_limit: int = 244
) -> List[str]:
    """
    Build the list of TO_HOST packets for a Scratch CloudRequest.

    - request_name: e.g. "my_func"
    - args: list of string args (will be joined with "&")
    - request_id: 8‑char ID Scratch assigns, e.g. "A1B2C3D49"
    - length_limit: max chars per packet chunk (default 244)
    
    Returns a list of strings like ["-part1.A1B2C3D49", "part2.A1B2C3D49"].
    """
    # 1) Construct the raw request: "name&arg1&arg2&..."
    raw = request_name
    if args:
        raw += "&" + "&".join(args)

    # 2) Encode exactly as CloudRequests.on_set expects
    encoded = Encoding.encode(raw)

    packets: List[str] = []
    # 3) Slice into chunks of at most length_limit
    while encoded:
        chunk, encoded = encoded[:length_limit], encoded[length_limit:]
        # All but the final chunk get a "-" prefix
        prefix = "-" if encoded else ""
        packets.append(f"{prefix}{chunk}.{request_id}0")

    return packets
def sanitize_keys(d: dict) -> dict:
    return {''.join(c for c in str(k) if c.isalnum()): v for k, v in d.items()}
def get_from_host_vars(cloud):
    result = []
    clouddata = sanitize_keys(cloud.get_all_vars(use_logs=True))
    del clouddata["TOHOST"]
    clouddata = sorted(clouddata.items(),key=lambda n:n[0][-1])
    clouddata = [n[1] for n in clouddata]
    for n in clouddata:
        result.append(n)
    return result
def receive(cloud,id):
    result = None
    loop = True
    decoder = ResponseDecoder()
    while loop:
        host_vars = get_from_host_vars(cloud)
        for host_var in host_vars:
            data = decoder.decode_chunk(host_var,allowed_ids={id + "0"})
            if data:
                loop = False
                break
    return data
def send(cloud,name,args=[],id=str(randint(10001,99999))):
    data = generate_request_packets(name,args,request_id=id)
    for i in data:
        cloud.set_var("TO_HOST",i)

def cloud_request(cloud,name,args=[]):
    id = str(randint(10001,99999))
    send(cloud,name,args,id=id)
    return receive(cloud,id)

