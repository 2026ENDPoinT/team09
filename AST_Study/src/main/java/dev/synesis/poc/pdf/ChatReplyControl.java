package dev.synesis.poc.pdf;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.awt.*;
import javax.swing.*;

/** One reply only. Never invalidates another process or a completed result. */
final class ChatReplyControl {
    static final class Cancelled extends IOException {
        Cancelled() { super("답변 생성이 중지됐어요."); }
    }
    private volatile boolean cancelled;
    private Process worker;
    private Path result;
    boolean cancelled() { return cancelled; }
    synchronized void prepare(Path result) throws Cancelled {
        this.result=result;
        if(cancelled)throw new Cancelled();
    }
    synchronized void attach(Process worker) {
        this.worker=worker;
        if(cancelled&&!completed())worker.toHandle().destroy();
    }
    synchronized void detach() { worker=null; }
    synchronized boolean completed() { return result!=null&&Files.isRegularFile(result); }
    synchronized void cancel() {
        if(cancelled)return;
        cancelled=true;
        if(completed())return;
        // ProcessHandle sends SIGTERM without closing the stdout pipe. The worker
        // can still publish an already completed answer before exiting.
        if(worker!=null)worker.toHandle().destroy();
    }
    void check() throws Cancelled { if(cancelled&&!completed())throw new Cancelled(); }
    static Icon stopIcon() { return new Icon() {
        public int getIconWidth(){return 16;}
        public int getIconHeight(){return 16;}
        public void paintIcon(Component c,Graphics graphics,int x,int y){
            Graphics2D g=(Graphics2D)graphics.create();g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setColor(Color.WHITE);g.setStroke(new BasicStroke(1.8f,BasicStroke.CAP_ROUND,BasicStroke.JOIN_ROUND));
            g.drawLine(x+4,y+4,x+12,y+12);g.drawLine(x+12,y+4,x+4,y+12);g.dispose();
        }
    }; }
}
