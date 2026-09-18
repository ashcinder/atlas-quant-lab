import httpx
from app.supervisor_client import SupervisorClient


def test_loopback_rpc_bypasses_environment_proxy(monkeypatch):
    calls = []
    def post(url, **kwargs):
        calls.append(kwargs['trust_env'])
        return httpx.Response(200, json={'result': '0x41b'}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', post)
    assert SupervisorClient().status().connected
    SupervisorClient('https://example.com').status()
    assert calls == [False, False, True, True]


def test_rpc_timeout_allows_slow_local_genesis_reads(monkeypatch):
    def post(url, **kwargs):
        assert kwargs['timeout'] >= 5
        return httpx.Response(200, json={'result': {'hash':'0x'+'a'*64}}, request=httpx.Request('POST', url))
    monkeypatch.setattr(httpx, 'post', post)
    assert SupervisorClient()._call('eth_getBlockByNumber', ['0x0',False])['hash']


def test_missing_result_only_means_not_found_for_transaction_lookups(monkeypatch):
    import pytest
    from app.supervisor_client import SupervisorRPCError
    monkeypatch.setattr(httpx, 'post', lambda url,**kwargs: httpx.Response(200,json={'jsonrpc':'2.0','id':1},request=httpx.Request('POST',url)))
    assert SupervisorClient().transaction('0x'+'a'*64) is None
    with pytest.raises(SupervisorRPCError):SupervisorClient()._call('eth_getBalance', [])


def test_rate_limit_retries_reads_but_never_resubmits_writes(monkeypatch):
    import pytest
    import app.supervisor_client as module
    calls=[]
    monkeypatch.setattr(module.time,'sleep',lambda seconds:None)
    def post(url,**kwargs):
        calls.append(kwargs['json']['method'])
        return httpx.Response(429 if len(calls)==1 else 200,json={'result':'0x1'},request=httpx.Request('POST',url))
    monkeypatch.setattr(httpx,'post',post)
    assert SupervisorClient()._call('eth_blockNumber',[])=='0x1'
    assert len(calls)==2
    calls.clear()
    with pytest.raises(module.SupervisorRPCError):SupervisorClient().submit_signed_transaction('0x01')
    assert len(calls)==1
