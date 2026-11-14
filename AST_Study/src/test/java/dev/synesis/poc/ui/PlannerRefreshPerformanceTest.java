package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import static dev.synesis.poc.planner.PlannerModel.*;
import javax.swing.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.time.*;
import java.util.List;
import java.util.concurrent.TimeUnit;

/** Uses a locked fixture store to ensure periodic IO cannot block the EDT or overwrite a later edit. */
public final class PlannerRefreshPerformanceTest {
    public static void main(String[] args)throws Exception{
        PlannerStore store=new PlannerStore(Files.createTempDirectory("synesis-planner-refresh-").resolve("planner.json"));
        Clock clock=Clock.fixed(Instant.parse("2026-10-27T03:00:00Z"),ZoneId.of("Asia/Seoul"));
        PlannerDesign[] view={null};JPanel parent=new JPanel(){@Override public boolean isShowing(){return true;}};
        try{
            SwingUtilities.invokeAndWait(()->{
                view[0]=new PlannerDesign(store,clock);parent.add(view[0]);
                ComponentSnapshot.check(view[0]);
            });
            Method mutex=PlannerStore.class.getDeclaredMethod("mutex");mutex.setAccessible(true);Object lock=mutex.invoke(store);
            SwingWorker<?,?>[] first={null};
            synchronized(lock){
                SwingUtilities.invokeAndWait(()->{
                    parent.addNotify();first[0]=(SwingWorker<?,?>)get(view[0],"pendingRefresh");
                    check(first[0]!=null,"visible planner did not schedule a refresh");
                    for(int i=0;i<20;i++)view[0].refreshFromStore();
                    check(get(view[0],"pendingRefresh")==first[0],"refresh requests spawned parallel reads");
                });
                // This runs while the worker is waiting for the store mutex.
                SwingUtilities.invokeAndWait(()->check(!first[0].isDone(),"fixture did not block background IO"));
            }
            first[0].get(5,TimeUnit.SECONDS);
            // Keep EDT occupied until the old read finishes, then save/accept a newer state before done() runs.
            SwingUtilities.invokeAndWait(()->{try{
                view[0].refreshFromStore();SwingWorker<?,?> pending=(SwingWorker<?,?>)get(view[0],"pendingRefresh");pending.get(5,TimeUnit.SECONDS);
                view[0].accept(store.saveTask(new Task("fixture-task","새 할 일",LocalDate.now(clock),"",false)));
            }catch(Exception e){throw new RuntimeException(e);}});
            long until=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);
            boolean[] complete={false};
            while(System.nanoTime()<until){
                SwingUtilities.invokeAndWait(()->{
                    check(view[0].state.tasks().size()==1,"stale refresh overwrote local edit");
                    complete[0]=get(view[0],"pendingRefresh")==null;
                });
                if(complete[0])break;Thread.sleep(20);
            }
            check(complete[0],"coalesced refresh did not finish");
            // An unchanged periodic check must finish even while parsing/load is locked.
            synchronized(lock){
                SwingUtilities.invokeAndWait(()->{
                    for(var listener:view[0].refreshTimer.getActionListeners())listener.actionPerformed(new java.awt.event.ActionEvent(view[0],0,"periodic"));
                    first[0]=(SwingWorker<?,?>)get(view[0],"pendingRefresh");
                });
                check(first[0].get(2,TimeUnit.SECONDS)==null,"unchanged periodic check parsed the store");
            }
            // Wait for done() before the next tick so this checks file detection, not forced refresh.
            until=System.nanoTime()+TimeUnit.SECONDS.toNanos(5);boolean[] idle={false};
            while(System.nanoTime()<until){SwingUtilities.invokeAndWait(()->idle[0]=get(view[0],"pendingRefresh")==null);if(idle[0])break;Thread.sleep(20);}
            check(idle[0],"unchanged-store completion was not dispatched");
            store.saveTask(new Task("external-task","외부에서 추가한 할 일",LocalDate.now(clock),"",false));
            SwingUtilities.invokeAndWait(()->{
                for(var listener:view[0].refreshTimer.getActionListeners())listener.actionPerformed(new java.awt.event.ActionEvent(view[0],0,"periodic"));
                first[0]=(SwingWorker<?,?>)get(view[0],"pendingRefresh");
            });
            check(first[0].get(2,TimeUnit.SECONDS)!=null,"atomic external change was not read");
            SwingUtilities.invokeAndWait(()->{
                parent.removeNotify();check(!view[0].refreshTimer.isRunning(),"hidden planner keeps timer running");
            });
            System.out.println("PlannerRefreshPerformanceTest passed: reuse, non-blocking EDT, coalescing, stale read protection, unchanged-store IO skip, external change detection and hidden timer stop");
        }finally{if(view[0]!=null)SwingUtilities.invokeAndWait(view[0]::dispose);}
    }
    private static final class ComponentSnapshot {
        static void check(PlannerDesign view){
            Object calendar=view.calendar.getComponent(0);State old=view.state;
            view.accept(new State(1,old.events(),old.tags(),List.of(new Task("preview-task","할 일",LocalDate.now(view.clock),"",false)),old.goals(),false,old.deliveredReminders()));
            PlannerRefreshPerformanceTest.check(view.calendar.getComponent(0)==calendar,"task edit rebuilt calendar");
            view.accept(new State(2,old.events(),List.of(new Tag("tag-fixture","새 태그")),old.tasks(),old.goals(),false,old.deliveredReminders()));
            PlannerRefreshPerformanceTest.check(view.calendar.getComponent(0)!=calendar,"tag edit did not rebuild calendar");
            view.accept(old);
        }
    }
    private static Object get(Object o,String name){try{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}catch(Exception e){throw new RuntimeException(e);}}
    private static void check(boolean value,String message){if(!value)throw new AssertionError(message);}
}
