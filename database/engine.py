"""MongoDB-backed async session/query adapter used by Nexora File Store."""
from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorClient

from config import settings
from database.mongo_compat import (
    Base, Field, ModelSpec, CountSpec, LabelSpec, Query, func, select,
    Mapped, mapped_column, relationship,
)

_client = None
_db = None


def _mongo_db():
    global _client, _db
    if _client is None:
        _client = AsyncIOMotorClient(settings.mongo_uri)
        _db = _client[settings.mongo_database]
    return _db


class ScalarResult:
    def __init__(self, values): self._values = values
    def all(self): return self._values
    def first(self): return self._values[0] if self._values else None


class QueryResult:
    def __init__(self, rows): self._rows = rows
    def all(self): return self._rows
    def first(self): return self._rows[0] if self._rows else None
    def scalars(self):
        return ScalarResult([r[0] if isinstance(r, tuple) and r else r for r in self._rows])
    def scalar_one_or_none(self):
        if not self._rows: return None
        r=self._rows[0]
        return r[0] if isinstance(r,tuple) else r


class MongoSession:
    def __init__(self):
        self._pending=[]; self._loaded={}; self._deleted=[]
    async def __aenter__(self): return self
    async def __aexit__(self, exc_type, exc, tb):
        if exc_type is None: await self.commit()
        else: await self.rollback()
        return False
    def add(self,obj):
        if obj not in self._pending: self._pending.append(obj)
    async def delete(self,obj):
        if obj not in self._deleted: self._deleted.append(obj)
    async def flush(self): await self._persist_pending()
    async def rollback(self): self._pending.clear(); self._deleted.clear()
    async def get(self, model, ident, **kwargs):
        doc=await _mongo_db()[model.__tablename__].find_one({'id':ident})
        if not doc: return None
        obj=model._from_doc(doc); self._loaded[(model,ident)]=obj; return obj
    async def execute(self, query): return QueryResult(await _execute_query(_mongo_db(),query,self))
    async def scalar(self, query): return (await self.execute(query)).first()
    async def commit(self):
        await self._persist_pending()
        db=_mongo_db()
        for obj in list(self._loaded.values()):
            if obj not in self._deleted and obj not in self._pending and getattr(obj,'id',None) is not None:
                await _save_object(db,obj)
        for obj in self._deleted:
            await _delete_object(db,obj)
        self._deleted.clear()
    async def _persist_pending(self):
        db=_mongo_db()
        for obj in self._pending:
            await _save_object(db,obj)
            if getattr(obj,'id',None) is not None: self._loaded[(type(obj),obj.id)]=obj
        self._pending.clear()

async def _save_object(db,obj):
    cls=type(obj)
    if getattr(obj,'id',None) is None:
        last=await db[cls.__tablename__].find_one(sort=[('id',-1)])
        obj.id=(last.get('id',0)+1) if last else 1
    await db[cls.__tablename__].replace_one({'id':obj.id},obj._to_doc(),upsert=True)

async def _delete_object(db,obj):
    cls=type(obj)
    await db[cls.__tablename__].delete_one({'id':getattr(obj,'id',None)})
    if cls.__name__=='Bot':
        for name in Base._model_names:
            model=Base._models[name]
            if model is not cls and 'bot_id' in getattr(model,'_fields',{}):
                await db[model.__tablename__].delete_many({'bot_id':obj.id})


def _project(items, envs, query):
    if len(query.items)==1 and isinstance(query.items[0],ModelSpec):
        return items[0]
    vals=[]
    for spec in query.items:
        if isinstance(spec,CountSpec):
            vals.append(sum(1 for e in envs if spec.target is None or spec.target.value(e) is not None))
        elif isinstance(spec,Field): vals.append(spec.value(envs[0]))
        elif isinstance(spec,LabelSpec): vals.append(spec.value(envs[0]))
        else: vals.append(spec)
    return tuple(vals)


def _sort_value(expr,row):
    if isinstance(expr,CountSpec): return row[1] if isinstance(row,tuple) and len(row)>1 else 0
    if isinstance(expr,LabelSpec): return row[expr.index] if isinstance(row,tuple) and len(row)>expr.index else 0
    if isinstance(expr,Field): return getattr(row,expr.name,None) if not isinstance(row,tuple) else 0
    return 0

async def _execute_query(db,query,session):
    base=query.base_model
    if base is None: return []
    docs=await db[base.__tablename__].find({}).to_list(length=None)
    base_objs=[base._from_doc(d) for d in docs]
    for o in base_objs:
        if getattr(o,'id',None) is not None: session._loaded[(base,o.id)]=o
    envs=[{base:o} for o in base_objs]

    for join_model,onclause,outer in query.joins:
        jdocs=await db[join_model.__tablename__].find({}).to_list(length=None)
        jobs=[join_model._from_doc(d) for d in jdocs]
        new=[]
        for env in envs:
            matches=[]
            for j in jobs:
                e=dict(env); e[join_model]=j
                if onclause is None:
                    root=env.get(base)
                    ok=getattr(root,'owner_id',None)==getattr(j,'id',None)
                else: ok=onclause.evaluate(e)
                if ok: matches.append(e)
            if matches: new.extend(matches)
            elif outer: new.append(dict(env))
        envs=new

    if query.conditions:
        envs=[e for e in envs if all(c.evaluate(e) for c in query.conditions)]

    if query.group_fields:
        groups={}
        for e in envs:
            key=tuple(f.value(e) for f in query.group_fields); groups.setdefault(key,[]).append(e)
        rows=[_project([g[0].get(base)],g,query) for g in groups.values()]
    elif len(query.items) == 1 and isinstance(query.items[0], CountSpec):
        rows=[_project([envs[0].get(base)] if envs else [None], envs, query)]
    else:
        rows=[]
        for e in envs:
            root=e.get(base)
            rows.append(_project([root], [e], query))

    for order in reversed(query.orders):
        rows.sort(key=lambda r:_sort_value(order.expr,r),reverse=order.reverse)
    if query.offset_n: rows=rows[query.offset_n:]
    if query.limit_n is not None: rows=rows[:query.limit_n]
    return rows

class _SessionFactory:
    def __call__(self): return MongoSession()
AsyncSessionLocal=_SessionFactory()

async def init_db():
    db=_mongo_db()
    indexes={
        'owners':[[('telegram_id',1)]],
        'bots':[[('bot_token',1)],[('owner_id',1)]],
        'clone_users':[[('bot_id',1),('user_id',1)]],
        'nexora_wallets':[[('user_id',1)]],
        'nexora_gift_codes':[[('code',1)]],
        'nexora_referrals':[[('referred_user_id',1)]],
        'main_bot_channels':[[('chat_id',1)]],
    }
    for coll,specs in indexes.items():
        for keys in specs:
            try: await db[coll].create_index(keys)
            except Exception: pass

__all__=['AsyncSessionLocal','init_db','select','func','Base','Mapped','mapped_column','relationship']
