package dev.synesis.poc.pdf;

import java.util.concurrent.Semaphore;
import java.util.concurrent.atomic.AtomicBoolean;

/** One fair admission shared by imports and every study workspace in this app. */
final class PdfStudyQueue {
    private static final PdfStudyQueue GLOBAL=new PdfStudyQueue();
    private final Semaphore admission=new Semaphore(1,true);
    static PdfStudyQueue global(){return GLOBAL;}
    int waitingCount(){return admission.getQueueLength();}

    Permit acquire() throws InterruptedException {
        admission.acquire();
        return new Permit();
    }

    final class Permit implements AutoCloseable {
        private final AtomicBoolean released=new AtomicBoolean();
        @Override public void close(){if(released.compareAndSet(false,true))admission.release();}
    }
}
