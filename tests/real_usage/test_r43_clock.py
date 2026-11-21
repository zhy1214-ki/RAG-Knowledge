"""R4.3 offline clock regression tests; isolated SQLite, no live credentials or network."""
from datetime import datetime
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from unittest.mock import Mock
import pytest
import sqlalchemy as sa
from app.core.db import make_database
from app.core.errors import AppError
from app.real_usage.guard import UsageGuard, GuardState, ModelCall, Operation

class Clock:
    def __init__(self, value="2027-01-15T12:00:00+00:00"):
        self.wall=datetime.fromisoformat(value).timestamp(); self.tick=1000.0
        self.wall_read_delay=0.0;self.after_read_delay=0.0
    def advance(self, seconds, wall_seconds=None):
        self.tick+=seconds;self.wall+=seconds if wall_seconds is None else wall_seconds
    def read_wall(self):
        self.advance(self.wall_read_delay)
        result=self.wall
        self.advance(self.after_read_delay)
        return result
    def read_tick(self):return self.tick

@pytest.fixture
def rig(settings,tmp_path):
    cfg=settings.model_copy(update={'strict_clock_protection':True,'max_calls_total':1000,'max_embedding_calls_total':1000,'max_qwen_calls_total':1000,'model_requests_per_minute':5,'daily_budget_cny':Decimal('0.10'),'monthly_budget_cny':Decimal('3')})
    engine,sessions=make_database('sqlite:///'+(tmp_path/'clock.sqlite').as_posix())
    clock=Clock();g=UsageGuard(engine,sessions,cfg,clock=clock.read_wall,monotonic=clock.read_tick)
    yield g,clock,engine,sessions
    engine.dispose()

def restart(rig):
    g,c,e,s=rig
    return UsageGuard(e,s,g.cfg,clock=c.read_wall,monotonic=c.read_tick)

def embed(g,send=None):return g.execute('/embeddings',{'input':['abcdefgh']},send or (lambda _: {'usage':{'prompt_tokens':1}}),'EMBEDDING_ERROR')

def deny(g):
    send=Mock()
    with pytest.raises(AppError) as error:embed(g,send)
    assert error.value.code=='USAGE_STOPPED';send.assert_not_called()

@pytest.mark.parametrize('offset',[0.063,0.066,0.069])
def test_slow_wall_correction_then_immediate_operation_and_model(rig,offset):
    g,c,_,s=rig
    prior=c.wall;c.advance(1200,1200-offset) # Wall progresses; its offset slowly changes, it never reverses.
    assert c.wall>prior
    op=g.begin_operation('synthetic','kb','message','clock-regression')
    send=Mock(return_value={'usage':{'prompt_tokens':1}})
    embed(g,send);g.finish_operation(op,True)
    send.assert_called_once()
    with s() as db:
        assert not db.get(GuardState,1).stopped
        assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==1


@pytest.mark.parametrize('delay',[0.063,0.066,0.069])
@pytest.mark.parametrize('position',['wall_read_delay','after_read_delay'])
def test_measured_sampling_delay_is_not_a_rollback(rig,delay,position):
    g,c,_,s=rig;setattr(c,position,delay)
    for index in range(3):
        op=g.begin_operation('synthetic','kb','message',str(index))
        embed(g);g.finish_operation(op,True);c.advance(1)
    assert g.summary()['r1_reserved_attempts']==3 and not g.summary()['stopped']


def test_repeated_slew_samples_and_transactions_remain_monotonic(rig):
    g,c,_,s=rig;created=[]
    for index in range(20):
        c.advance(61,60.9967)
        op=g.begin_operation('synthetic','kb','message',str(index))
        embed(g);g.finish_operation(op,True)
        with s() as db:created.append(db.get(GuardState,1).last_observed_at)
    assert created==sorted(created)
    assert g.summary()['r1_reserved_attempts']==20 and not g.summary()['stopped']


@pytest.mark.parametrize('seconds',[0.001,0.069,1,61])
def test_observed_real_wall_rollback_still_blocks_before_send(rig,seconds):
    g,c,_,s=rig;embed(g);c.wall-=seconds;deny(g)
    with s() as db:
        assert db.get(GuardState,1).reason=='CLOCK_REVIEW_REQUIRED'
        assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==1


@pytest.mark.parametrize('drift',[-61,61])
@pytest.mark.parametrize('delay',[0,0.069])
def test_large_drift_cannot_hide_inside_sampling_uncertainty(rig,drift,delay):
    g,c,_,s=rig;c.advance(120,120+drift);c.after_read_delay=delay
    deny(g)
    with s() as db:assert db.get(GuardState,1).reason=='CLOCK_REVIEW_REQUIRED'


def test_monotonic_rollback_is_untrusted(rig):
    g,c,_,_=rig;c.tick-=1;deny(g)


@pytest.mark.parametrize('field,value',[('wall',float('nan')),('wall',float('inf')),('tick',float('nan')),('tick',float('inf'))])
def test_invalid_live_clock_rejects_without_reservation(rig,field,value):
    g,c,_,s=rig;setattr(c,field,value);deny(g)
    with s() as db:
        assert db.get(GuardState,1).reason=='CLOCK_REVIEW_REQUIRED'
        assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==0


@pytest.mark.parametrize('bad',[-1,float('inf')])
def test_untrusted_checkpoint_is_not_replaced_on_restart(rig,bad):
    g,c,_,s=rig
    with s() as db:db.get(GuardState,1).last_observed_at=bad;db.commit()
    again=restart(rig);deny(again)
    with s() as db:
        row=db.get(GuardState,1)
        assert row.stopped and row.reason=='CLOCK_REVIEW_REQUIRED'
        assert row.last_observed_at==bad and row.clock_epoch==0
    with pytest.raises(AppError):again.acknowledge_stop(acknowledge_clock=True)


@pytest.mark.parametrize('reason',['CLOCK_REVIEW_REQUIRED','MODEL_OR_USAGE_UNCERTAIN','MANUAL_PAUSE'])
def test_existing_pause_is_never_automatically_cleared(rig,reason):
    g,c,_,s=rig;g.stop(reason);c.advance(10);again=restart(rig);deny(again)
    with s() as db:
        row=db.get(GuardState,1);assert row.stopped and row.reason==reason and row.clock_epoch==0


def test_old_ledger_and_unknown_cost_survive_clock_restart(rig):
    g,c,_,s=rig
    costs=['0.00005850','0.00003800','0.00134400','0.00189200','0.00181700']
    with s() as db:
        for index,cost in enumerate(costs):
            db.add(ModelCall(id='fictional-'+str(index),kind='qwen' if index==2 else 'embedding',created_at=c.wall,day='2027-01-15',status='UNKNOWN' if index==4 else 'VERIFIED',estimated_input=8,reserved_output=0,charge_cny=Decimal(cost)))
        row=db.get(GuardState,1);row.stopped=True;row.reason='CLOCK_REVIEW_REQUIRED';db.commit()
        before=[(x.id,x.status,x.charge_cny,x.created_at) for x in db.scalars(sa.select(ModelCall).order_by(ModelCall.id))]
    c.advance(86400);again=restart(rig);deny(again)
    with s() as db:
        after=[(x.id,x.status,x.charge_cny,x.created_at) for x in db.scalars(sa.select(ModelCall).order_by(ModelCall.id))]
        assert after==before and db.get(GuardState,1).clock_epoch==0
    assert again.summary()['cumulative_attempt_upper_bound']==11
    assert Decimal(again.summary()['estimated_reserved_cny'])==Decimal('0.00514950')


def test_clock_ack_cannot_lower_a_checkpoint_newer_than_any_call(rig):
    g,c,_,s=rig;embed(g);c.advance(10);again=restart(rig)
    again.stop('CLOCK_REVIEW_REQUIRED');c.wall-=5
    with pytest.raises(AppError):again.acknowledge_stop(acknowledge_clock=True)
    with s() as db:
        row=db.get(GuardState,1);assert row.stopped and row.clock_epoch==0 and row.last_observed_at>c.wall


def test_operator_clock_ack_rejects_checkpoint_regression(rig,monkeypatch):
    import real_usage_runtime as runtime
    g,c,engine,s=rig;embed(g);c.advance(10);again=restart(rig)
    again.stop('CLOCK_REVIEW_REQUIRED');c.wall-=5
    monkeypatch.setattr(runtime,'database_url',lambda:'fictional-offline-db')
    monkeypatch.setattr('app.core.db.make_database',lambda _: (engine,s))
    monkeypatch.setattr('time.time',lambda:c.wall)
    monkeypatch.setattr('time.monotonic',lambda:c.tick)
    with pytest.raises(runtime.Stop,match='R4_CLOCK_BEFORE_PERSISTED_RECORD'):runtime.admin(True,True)
    with s() as db:assert db.get(GuardState,1).clock_epoch==0 and db.get(GuardState,1).stopped


@pytest.mark.parametrize('monotonic_advances',[False,True])
def test_suspend_resume_clock_relationship(rig,monotonic_advances):
    g,c,_,_=rig
    if monotonic_advances:
        c.advance(120);embed(g);assert not g.summary()['stopped']
    else:
        c.wall+=120;deny(g)


def test_unbounded_sampling_interval_fails_closed(rig):
    g,c,_,_=rig;c.after_read_delay=120;deny(g)


def test_concurrent_operation_checks_use_serialized_samples(rig):
    g,c,_,s=rig;c.advance(1200,1199.934);barrier=Barrier(2)
    def worker(digest):
        barrier.wait(timeout=5)
        try:return ('OK',g.begin_operation('synthetic','kb','message',digest))
        except AppError as error:return (error.code,None)
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(worker,['first','second']))
    assert sorted(code for code,_ in results)==['OK','USAGE_BUSY']
    for code,op in results:
        if code=='OK':g.finish_operation(op,True)
    with s() as db:assert not db.get(GuardState,1).stopped


@pytest.mark.parametrize('kind',['embedding','qwen'])
def test_paid_provider_entry_cannot_bypass_clock_pause(rig,kind):
    from app.real_usage.models import GuardedModels
    g,c,_,s=rig;c.wall-=1;deny(g)
    factory=Mock();models=GuardedModels(g.cfg,g,factory)
    with pytest.raises(AppError) as error:
        if kind=='embedding':models.embed(['synthetic'])
        else:models.answer('synthetic',[{'text':'synthetic fact','source_id':1}],[])
    assert error.value.code=='USAGE_STOPPED';factory.assert_not_called()
    with s() as db:assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==0


def test_background_indexing_cannot_bypass_clock_pause(rig,tmp_path):
    from types import SimpleNamespace
    from threading import RLock
    from app.models import Base,User,KnowledgeBase,Document
    from app.real_usage.models import GuardedModels
    from app.services.documents import process_document
    g,c,engine,s=rig;c.wall-=1;deny(g)
    Base.metadata.create_all(engine);file=tmp_path/'synthetic.txt';file.write_text('Synthetic clock test.',encoding='utf-8')
    with s() as db:
        user=User(username='r43_synthetic',password_hash='fictional-not-a-login-credential');db.add(user);db.flush()
        kb=KnowledgeBase(owner_id=user.id,name='clock-only');db.add(kb);db.flush()
        doc=Document(knowledge_base_id=kb.id,name='synthetic.txt',file_path=str(file),file_type='txt',size=file.stat().st_size);db.add(doc);db.commit();docid=doc.id
    cfg=g.cfg.model_copy(update={'vector_backend':'memory','vector_uri':'unused','storage_dir':tmp_path})
    factory=Mock();state=SimpleNamespace(lock=RLock(),sessions=s,settings=cfg,models=GuardedModels(cfg,g,factory),vectors=None)
    process_document(state,docid)
    factory.assert_not_called()
    with s() as db:
        doc=db.get(Document,docid);assert doc.status=='failed' and doc.error_code=='USAGE_STOPPED'
        assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==0
        assert db.get(GuardState,1).reason=='CLOCK_REVIEW_REQUIRED'


def test_clock_fault_then_corrected_restart_stays_paused(rig):
    g,c,_,s=rig;c.wall-=1;deny(g);c.advance(2)
    again=restart(rig);deny(again)
    with pytest.raises(AppError):again.acknowledge_stop()
    with s() as db:
        row=db.get(GuardState,1);assert row.stopped and row.reason=='CLOCK_REVIEW_REQUIRED' and row.clock_epoch==0
        assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==0


def test_manual_clock_ack_brackets_sampling_without_refunding(rig):
    g,c,_,s=rig;embed(g);reserved=g.summary()['estimated_reserved_cny'];c.advance(61)
    c.wall+=3600;deny(g);c.wall-=3600;c.after_read_delay=0.069
    g.acknowledge_stop(acknowledge_clock=True)
    assert g.summary()['clock_epoch']==1 and g.summary()['estimated_reserved_cny']==reserved
    embed(g)
    with s() as db:assert db.scalar(sa.select(sa.func.count()).select_from(ModelCall))==2


@pytest.mark.parametrize('bad',[-1,float('inf')])
def test_untrusted_ledger_time_keeps_unknown_and_checkpoint(rig,bad):
    g,c,_,s=rig
    with s() as db:
        floor=db.get(GuardState,1).last_observed_at
        db.add(ModelCall(id='fictional-bad-time',kind='embedding',created_at=bad,day='invalid-display',status='UNKNOWN',estimated_input=8,reserved_output=0,charge_cny=Decimal('0.000004')));db.commit()
    again=restart(rig);deny(again)
    with s() as db:
        row=db.get(GuardState,1);call=db.get(ModelCall,'fictional-bad-time')
        assert row.stopped and row.reason=='CLOCK_REVIEW_REQUIRED' and row.last_observed_at==floor
        assert call.created_at==bad and call.status=='UNKNOWN' and call.charge_cny==Decimal('0.000004')


@pytest.mark.parametrize('bad',[float('nan'),float('inf')])
def test_invalid_startup_sample_cannot_create_a_fresh_window(rig,bad):
    g,c,_,s=rig;c.wall=bad;again=restart(rig);deny(again)
    assert again.summary()['stopped'] and again.summary()['reason']=='CLOCK_REVIEW_REQUIRED'
    with s() as db:assert db.get(GuardState,1).clock_epoch==0
