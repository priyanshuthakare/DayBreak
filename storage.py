"""Persistent storage; every ticket query is scoped to a verified user or organization."""

from datetime import datetime

from sqlalchemy import Column, DateTime, ForeignKey, Index, JSON, MetaData, String, Table, create_engine, delete, insert, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

metadata = MetaData()
owners = Table('queue_owners', metadata, Column('id', String(255), primary_key=True))
tickets = Table(
    'tickets', metadata,
    Column('id', String(36), primary_key=True),
    Column('owner_id', String(255), ForeignKey('queue_owners.id'), nullable=False),
    Column('created_at', DateTime(timezone=True), nullable=False),
    Column('payload', JSON, nullable=False),
)
Index('ix_tickets_owner_created', tickets.c.owner_id, tickets.c.created_at)


def create_store(database_url):
    kwargs = {'pool_pre_ping': True}
    if database_url.startswith('sqlite:'):
        kwargs['connect_args'] = {'check_same_thread': False, 'timeout': 30}
    engine = create_engine(database_url, **kwargs)
    metadata.create_all(engine)
    return engine


def lock_queue(conn, owner):
    # All queue-changing operations take the same per-owner lock. The INSERT is
    # also a SQLite write lock; on PostgreSQL SELECT FOR UPDATE locks the row.
    dialect_insert = pg_insert if conn.dialect.name == 'postgresql' else sqlite_insert
    conn.execute(dialect_insert(owners).values(id=owner).on_conflict_do_nothing(index_elements=['id']))
    conn.execute(select(owners.c.id).where(owners.c.id == owner).with_for_update()).first()


def list_tickets(engine, owner):
    with engine.connect() as conn:
        return [row.payload for row in conn.execute(
            select(tickets.c.payload).where(tickets.c.owner_id == owner)
            .order_by(tickets.c.created_at.desc(), tickets.c.id.desc())
        )]


def add_ticket(engine, owner, ticket):
    with engine.begin() as conn:
        lock_queue(conn, owner)
        conn.execute(insert(tickets).values(
            id=ticket['id'], owner_id=owner,
            created_at=datetime.fromisoformat(ticket['created_at']), payload=ticket,
        ))


def update_status(engine, owner, ticket_id, status):
    with engine.begin() as conn:
        lock_queue(conn, owner)
        row = conn.execute(select(tickets.c.payload).where(
            tickets.c.owner_id == owner, tickets.c.id == ticket_id
        )).first()
        if not row:
            return None
        ticket = dict(row.payload)
        ticket['status'] = status
        conn.execute(update(tickets).where(tickets.c.owner_id == owner, tickets.c.id == ticket_id).values(payload=ticket))
        return ticket


def delete_ticket(engine, owner, ticket_id):
    with engine.begin() as conn:
        lock_queue(conn, owner)
        result = conn.execute(delete(tickets).where(tickets.c.owner_id == owner, tickets.c.id == ticket_id))
        return result.rowcount == 1
