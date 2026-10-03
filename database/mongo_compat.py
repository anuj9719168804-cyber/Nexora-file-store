from __future__ import annotations
import datetime as dt
import copy

class Mapped:
    def __class_getitem__(cls, item): return cls

class Field:
    def __init__(self, name=None, default=None):
        self.name=name
        self.default=default
    def __get__(self, instance, owner):
        if instance is None: return self
        return instance.__dict__.get(self.name, copy.deepcopy(self.default() if callable(self.default) else self.default))
    def __set__(self, instance, value): instance.__dict__[self.name]=value
    def __eq__(self, other): return Condition(self,'eq',other)
    def __ne__(self, other): return Condition(self,'ne',other)
    def is_(self, other): return Condition(self,'eq',other)
    def in_(self, values): return Condition(self,'in',values)
    def asc(self): return Order(self,False)
    def desc(self): return Order(self,True)
    def value(self, env):
        for cls,obj in env.items():
            if self.name in getattr(cls,'_fields',{}): return getattr(obj,self.name,None)
        return None

class Condition:
    def __init__(self, field, op, other): self.field,self.op,self.other=field,op,other
    def evaluate(self, env):
        left=self.field.value(env); right=self.other.value(env) if hasattr(self.other,'value') else self.other
        if self.op=='eq': return left==right
        if self.op=='ne': return left!=right
        if self.op=='in': return left in right
        return False

class Order:
    def __init__(self,expr,reverse=False): self.expr,self.reverse=expr,reverse

class ModelSpec:
    def __init__(self,model): self.model=model

class CountSpec:
    def __init__(self,target=None): self.target=target
    def label(self,name): return LabelSpec(self,name,self)
    def desc(self): return Order(self,True)
    def asc(self): return Order(self,False)
    def value(self,env): return self.target.value(env) if self.target else 1

class LabelSpec:
    def __init__(self,expr,name,source=None): self.expr,self.name,self.source=expr,name,source or expr; self.index=1
    def desc(self): return Order(self,True)
    def asc(self): return Order(self,False)
    def value(self,env): return self.expr.value(env)

class Query:
    def __init__(self,*items):
        self.items=[ModelSpec(x) if isinstance(x,type) and hasattr(x,'__tablename__') else x for x in items]
        self.base_model=next((x.model for x in self.items if isinstance(x,ModelSpec)),None)
        if self.base_model is None:
            self.base_model=next((getattr(x,'owner',None) for x in self.items if isinstance(x,Field)),None)
        self.conditions=[]; self.orders=[]; self.joins=[]; self.group_fields=[]; self.limit_n=None; self.offset_n=0
    def where(self,*x): self.conditions.extend(x); return self
    def order_by(self,*x): self.orders.extend(x); return self
    def limit(self,n): self.limit_n=n; return self
    def offset(self,n): self.offset_n=n; return self
    def join(self,model,onclause=None): self.joins.append((model,onclause,False)); return self
    def outerjoin(self,model,onclause=None): self.joins.append((model,onclause,True)); return self
    def group_by(self,*x): self.group_fields.extend(x); return self
    def with_for_update(self): return self
    def select_from(self,model): self.base_model=model; return self

class Func:
    def count(self,target=None): return CountSpec(target)
    def now(self): return dt.datetime.now(dt.timezone.utc)
func=Func()
def select(*items): return Query(*items)

def mapped_column(*args, **kwargs):
    default=kwargs.get('default', None)
    if default is None and isinstance(kwargs.get('server_default'), dt.datetime):
        default=lambda: dt.datetime.now(dt.timezone.utc)
    elif default is None and kwargs.get('server_default') is not None:
        sd=kwargs.get('server_default')
        default=sd if not callable(sd) else None
    return Field('__pending__', default)
def relationship(*args, **kwargs): return None
class Base:
    _models={}; _model_names=[]
    def __init_subclass__(cls, **kwargs):
        super().__init_subclass__(**kwargs)
        fields={}
        for name,val in list(cls.__dict__.items()):
            if isinstance(val,Field):
                if val.name=='__pending__': val.name=name
                val.owner=cls
                fields[name]=val
        cls._fields=fields
        cls.__tablename__=getattr(cls,'__tablename__',cls.__name__.lower())
        Base._models[cls.__name__]=cls
        Base._model_names.append(cls.__name__)
    def __init__(self, **kwargs):
        for name,field in self._fields.items():
            if name in kwargs: setattr(self,name,kwargs[name])
            elif field.default is not None:
                d=field.default() if callable(field.default) else field.default
                setattr(self,name,copy.deepcopy(d))
        for k,v in kwargs.items(): setattr(self,k,v)
    @classmethod
    def _from_doc(cls,doc):
        obj=cls()
        for k,v in doc.items():
            if k!='_id': setattr(obj,k,v)
        return obj
    def _to_doc(self):
        doc={}
        for name in self._fields: doc[name]=getattr(self,name,None)
        return {k:v for k,v in doc.items() if v is not None}
