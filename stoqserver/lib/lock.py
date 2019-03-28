import logging

from gevent.lock import Semaphore

log = logging.getLogger(__name__)


class LockFailedException(Exception):
    pass


class base_lock_decorator:
    """Decorator to handle pinpad access locking.

    This will make sure that only one callsite is using the sat at a time.
    """
    lock = None

    def __init__(self, block):
        assert self.lock is not None
        self._block = block

    def __call__(self, func):

        def new_func(*args, **kwargs):
            acquired = self.lock.acquire(blocking=self._block)
            if not acquired:
                log.info('Failed %s in func %s' % (type(self).__name__, func))
                raise LockFailedException()

            try:
                return func(*args, **kwargs)
            finally:
                self.lock.release()

        return new_func


class lock_pinpad(base_lock_decorator):
    lock = Semaphore()


class lock_sat(base_lock_decorator):
    lock = Semaphore()
