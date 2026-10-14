from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """The request's database session, in one transaction.

    The transaction commits when the route returns and rolls back when it
    raises, as Polar's TransactionalMiddleware does. The services only flush:
    one that calls another stays in the same transaction.
    """
    async with request.app.state.sessionmaker() as session, session.begin():
        yield session


# scope="function": the transaction ends before the response is sent, so a
# client never gets a success for a commit that failed.
SessionDep = Annotated[AsyncSession, Depends(get_session, scope="function")]
