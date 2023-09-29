import threading
import datetime


class RegularTimer(threading.Thread):
    def __init__(self, dt=datetime.timedelta(milliseconds=1000)):
        self.cv = threading.Condition()
        self.running = True
        self.dt = datetime.timedelta(dt)
        self.next_update = datetime.datetime.now() + self.dt
        super().__init__()

    def update(self):
        pass

    def run(self):
        with self.cv:
            while self.running:
                dt = (self.next_update - datetime.datetime.now()).total_seconds()
                if (dt < 0):
                    self.update()
                    self.next_update = self.next_update + self.dt
                    dt = (self.next_update - datetime.datetime.now()).total_seconds()
                self.cv.wait(dt)

    def cancel(self):
        self.running = False
        with self.cv:
            self.cv.notify_all()
        self.join()
