package dev.synesis.poc.ui;

import javax.swing.*;
import java.util.LinkedHashSet;
import java.util.Set;

/** One EDT clock for short library effects. Idle screens run no timers and retain no snapshots. */
public final class LibraryMotionClock {
    public interface Task {boolean advance(long now);}
    private static final Set<Task> active=new LinkedHashSet<>();
    private static final Timer timer=new Timer(16,event->tick(System.nanoTime()));
    private static final double[] EASE=new double[129];
    static {
        timer.setCoalesce(true);
        for(int i=0;i<EASE.length;i++) {
            double x=i/(double)(EASE.length-1),lo=0,hi=1,t=x;
            for(int n=0;n<18;n++) {
                double u=1-t,value=3*u*u*t*.22+3*u*t*t*.36+t*t*t;
                if(value<x)lo=t;else hi=t;t=(lo+hi)/2;
            }
            EASE[i]=1-Math.pow(1-t,3);
        }
        EASE[0]=0;EASE[EASE.length-1]=1;
    }
    private LibraryMotionClock() {}
    public static boolean reduced(){return Boolean.getBoolean("synesis.reduceMotion")||Boolean.TRUE.equals(UIManager.get("synesis.reduceMotion"));}
    public static double ease(double t) {
        double x=Math.max(0,Math.min(1,t))*(EASE.length-1);
        int i=Math.min(EASE.length-2,(int)x);return EASE[i]+(EASE[i+1]-EASE[i])*(x-i);
    }
    public static boolean add(Task task) {
        if(!active.contains(task)&&active.size()>=48)return false;
        active.add(task);if(!timer.isRunning())timer.start();return true;
    }
    public static void remove(Task task){active.remove(task);if(active.isEmpty())timer.stop();}
    static void tick(long now) {
        for(Task task:active.toArray(Task[]::new))if(active.contains(task)&&!task.advance(now))active.remove(task);
        if(active.isEmpty())timer.stop();
    }
    static int activeCount(){return active.size();}
}
