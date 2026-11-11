"""Bounded PNG validation and independently audited image decisions."""
import asyncio
import base64
import binascii
from contextlib import closing
from hashlib import sha256
import json
import sqlite3
import struct
import uuid
import zlib
from datetime import UTC, datetime

from backend.decision_provider import ProviderFailure, parse_answer, request_body


def questions():
    action = request_body({})['questions'][0]
    action['name'] = 'action'
    return [action, dict(type='choice', name='crossover',
        instructions='At the last selected candle, inspect the blue short SMA and amber long SMA in the PNG. '
        'Is an upward crossover, downward crossover, or no crossover visible? Judge the image itself; '
        'do not copy the JSON crossover. Choose unreadable if the image lacks enough visible history or readable lines.',
        choices=[dict(value=v, description=d) for v,d in [
            ('up','Short SMA crosses above long SMA at the cutoff.'),
            ('down','Short SMA crosses below long SMA at the cutoff.'),
            ('none','No crossover at the selected candle.'),('unreadable','Cannot read the signal from this image.')]]),
        dict(type='choice', name='evidence',
            instructions='Is the visible chart sufficient to assess the SMA crossover at the cutoff? '
            'Check legibility, prior line context and the selected candle. Unknown volume is explicitly permitted; '
            'it is not zero and does not itself prevent a price SMA assessment.',
            choices=[dict(value=v,description=d) for v,d in [
                ('sufficient','Readable candles and both SMA lines with enough context at cutoff.'),
                ('insufficient','Not enough visible history or signal evidence.'),
                ('unreadable','Image or plotted lines cannot be read.')]])]


def manifest(saved):
    s=saved['snapshot']; rows=s['chart']['candles']
    return dict(snapshot_id=s['snapshot_id'],snapshot_sha256=saved['sha256'],symbol=s['symbol'],
        interval=s['interval'],cutoff=s['decision_time'],range_start=rows[0]['timestamp'] if rows else None,
        range_end=rows[-1]['timestamp'] if rows else None)


def decode_png(url):
    """Decode canvas RGB/RGBA PNG fully, including CRC, inflate and scanline filters.

    Bound memory before inflate. The embedded manifest detects accidental image/
    snapshot swaps; it is not an authentication mechanism for arbitrary clients.
    """
    try:
        if not isinstance(url,str) or not url.startswith('data:image/png;base64,') or len(url)>8_000_000:
            raise ValueError()
        raw=base64.b64decode(url.split(',',1)[1],validate=True)
        if raw[:8]!=b'\x89PNG\r\n\x1a\n':raise ValueError()
        offset=8; compressed=bytearray(); binding=None; size=None; ended=False; seen_idat=False
        while offset<len(raw):
            length=struct.unpack('>I',raw[offset:offset+4])[0]
            kind=raw[offset+4:offset+8]; data=raw[offset+8:offset+8+length]
            crc=struct.unpack('>I',raw[offset+8+length:offset+12+length])[0]
            if binascii.crc32(kind+data)&0xffffffff!=crc:raise ValueError()
            if size is None and kind!=b'IHDR':raise ValueError()
            if kind==b'IHDR':
                if size is not None:raise ValueError()
                w,h,depth,color,compression,filtering,interlace=struct.unpack('>IIBBBBB',data)
                if not (64<=w<=4096 and 64<=h<=4096 and w*h<=6_000_000):raise ValueError()
                if depth!=8 or color not in (2,6) or compression or filtering or interlace:raise ValueError()
                size=(w,h,3 if color==2 else 4)
            elif kind==b'IDAT':compressed.extend(data);seen_idat=True
            elif kind==b'tEXt' and data.startswith(b'arbitrade_snapshot\x00'):
                if binding is not None:raise ValueError()
                binding=json.loads(data.split(b'\x00',1)[1])
            elif kind==b'IEND':
                if length or offset+12!=len(raw):raise ValueError()
                ended=True;break
            elif kind[:1].isupper() and kind not in (b'PLTE',):raise ValueError()
            offset+=length+12
        if not ended or not seen_idat or size is None:raise ValueError()
        w,h,bpp=size;stride=w*bpp;expected=(stride+1)*h
        decoder=zlib.decompressobj();scan=decoder.decompress(bytes(compressed),expected+1)
        if len(scan)!=expected or not decoder.eof or decoder.unused_data:raise ValueError()
        prior=bytearray(stride);distinct=set()
        for y in range(h):
            pos=y*(stride+1);f=scan[pos];row=bytearray(scan[pos+1:pos+1+stride])
            if f>4:raise ValueError()
            for x in range(stride):
                a=row[x-bpp] if x>=bpp else 0;b=prior[x];c=prior[x-bpp] if x>=bpp else 0
                if f==1:v=a
                elif f==2:v=b
                elif f==3:v=(a+b)//2
                elif f==4:
                    p=a+b-c;pa,pb,pc=abs(p-a),abs(p-b),abs(p-c)
                    v=a if pa<=pb and pa<=pc else b if pb<=pc else c
                else:v=0
                row[x]=(row[x]+v)&255
            if len(distinct)<3:
                distinct.update(bytes(row[x:x+bpp]) for x in range(0,stride,bpp))
            prior=row
        if len(distinct)<2:raise ValueError()
        return raw, binding, dict(width=w,height=h,sha256=sha256(raw).hexdigest())
    except (ValueError,TypeError,KeyError,struct.error,zlib.error,OverflowError):
        raise ProviderFailure('invalid_image','recapture_readable_chart_png') from None


def setup(connection):
    connection.execute('''CREATE TABLE IF NOT EXISTS decision_images (
        decision_id TEXT PRIMARY KEY REFERENCES decisions(id), png BLOB, metadata_json TEXT,
        questions_json TEXT NOT NULL, answers_json TEXT, comparison TEXT NOT NULL)''')


async def decide_image(service,snapshot_id,capture):
    from backend.decisions import encoded, validate_proposal, explanation
    identifier=str(uuid.uuid4());provider=service.provider;qs=questions()
    result=dict(status='missing_input',validation_status='incomplete',error_code='snapshot_missing',
        proposal=None,quantity=None,explanation='Recapture a completed chart with its matching saved snapshot.',
        paper_order_eligible=0,answer_json=None)
    with closing(sqlite3.connect(service.path)) as c,c:
        c.execute('''INSERT INTO decisions (id,requested_snapshot_id,created_at,provider,model,model_call_kind,status,validation_status)
                     VALUES (?,?,?,?,?,?,'pending','not_evaluated')''',
                  (identifier,snapshot_id,datetime.now(UTC).isoformat(),provider.name,provider.model,provider.mode))
        c.execute('INSERT INTO decision_images VALUES (?,NULL,NULL,?,NULL,?)',(identifier,encoded(qs),'not_evaluated'))
    try:
        saved=service.get_snapshot(snapshot_id);s=saved['snapshot']
        with closing(sqlite3.connect(service.path)) as c,c:
            c.execute('UPDATE decisions SET snapshot_id=?,market_data_kind=? WHERE id=?',
                      (snapshot_id,s['provenance']['market_data_kind'],identifier))
        if not s['completeness']['complete']:
            raise ProviderFailure('missing_input','recapture_complete_snapshot')
        if not capture:raise ProviderFailure('invalid_image','recapture_missing_png')
        raw,binding,meta=await asyncio.to_thread(decode_png,capture.get('image_url'))
        if binding!=manifest(saved) or capture.get('manifest')!=binding:
            raise ProviderFailure('snapshot_mismatch','recapture_matching_snapshot_and_range')
        meta.update(manifest=binding)
        with closing(sqlite3.connect(service.path)) as c,c:
            c.execute('UPDATE decision_images SET png=?,metadata_json=? WHERE decision_id=?',(raw,encoded(meta),identifier))
        response=await asyncio.wait_for(asyncio.to_thread(provider.decide_image,json.loads(encoded(s)),capture['image_url'],qs),provider.timeout+1)
        answers=response.get('answers') if isinstance(response,dict) else None
        if not isinstance(answers,list) or len(answers)!=3 or any(not isinstance(a,dict) for a in answers):
            raise ProviderFailure('malformed_answer','expected_three_named_answers')
        by_name={a.get('name'):a for a in answers}
        if set(by_name)!=set(q['name'] for q in qs):raise ProviderFailure('malformed_answer','missing_or_duplicate_named_answer')
        normalized={q['name']:parse_answer(dict(model=response.get('model'),answers=[by_name[q['name']]]),
            provider.model,q['name'],tuple(v['value'] for v in q['choices'])) for q in qs}
        visual=normalized['crossover']['choice'];evidence=normalized['evidence']['choice'];action=normalized['action']['choice']
        actual=s['indicators']['crossover'] or 'none'
        comparison='unreadable' if visual=='unreadable' or evidence=='unreadable' else 'insufficient' if evidence!='sufficient' else 'match' if visual==actual else 'conflict'
        valid,reason,quantity=validate_proposal(s,action)
        status='valid' if valid else 'invalid_proposal'
        if comparison!='match':status={'unreadable':'unreadable_image','insufficient':'insufficient_evidence','conflict':'conflicting_signal'}[comparison]
        result.update(status=status,validation_status='valid' if valid and comparison=='match' else 'rejected',
            error_code=None if status=='valid' else 'account_rule_violation' if comparison=='match' else 'recapture_or_review_'+comparison,
            proposal=action,quantity=quantity,answer_json=encoded(normalized['action']),
            explanation=explanation(s,action,reason)+f' Visual claim: {visual}; Python crossover: {actual}; evidence: {evidence}; comparison: {comparison}.',
            paper_order_eligible=0)
        with closing(sqlite3.connect(service.path)) as c,c:
            c.execute('UPDATE decision_images SET answers_json=?,comparison=? WHERE decision_id=?',(encoded(normalized),comparison,identifier))
    except ProviderFailure as error:
        result.update(status=error.status,validation_status='not_evaluated',error_code=error.code,explanation='Chart analysis unavailable: '+error.code+'. Recapture the selected completed chart if needed.')
    except TimeoutError:
        result.update(status='timeout',error_code='provider_timeout',explanation='Provider timed out; no paper order sent.')
    except ValueError:
        pass
    except Exception:
        result.update(status='provider_error',error_code='provider_failed',explanation='Provider request failed; no paper order sent.')
    with closing(sqlite3.connect(service.path)) as c,c:
        c.execute('UPDATE decisions SET '+','.join(k+'=?' for k in result)+' WHERE id=?',(*result.values(),identifier))
    from backend.decision_review import review_decision
    return await review_decision(service,identifier)
