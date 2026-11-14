package dev.synesis.poc.pdf;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.*;
import java.lang.management.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.function.*;
import javax.swing.*;
import com.google.gson.*;

/** Injected Window facts, actual Swing timers and widget painting. No Window, API or real job. */
public final class SummaryAnimationWindowTest {
 static final com.sun.management.OperatingSystemMXBean OS=(com.sun.management.OperatingSystemMXBean)ManagementFactory.getOperatingSystemMXBean();
 static final ThreadMXBean THREAD=ManagementFactory.getThreadMXBean();
 static final List<Map<String,Object>> rows=new ArrayList<>();static Fixture f;static long edtId;
 static void edt(Runnable task)throws Exception{SwingUtilities.invokeAndWait(task);}
 static Object get(Object o,String name)throws Exception{Field field=o.getClass().getDeclaredField(name);field.setAccessible(true);return field.get(o);}
 static void sync(Object o)throws Exception{Method method=o.getClass().getDeclaredMethod("syncTimer");method.setAccessible(true);method.invoke(o);}
 public static void main(String[] args)throws Exception {
  Path out=Path.of(args[0]);Files.createDirectories(out);
  edt(()->{try{edtId=Thread.currentThread().threadId();f=new Fixture();}catch(Exception e){throw new RuntimeException(e);}});
  Thread.sleep(180);
  phase("active-running",220,()->{});
  phase("inactive-running",220,()->{f.active=false;f.sync();});
  phase("iconified-running",220,()->{f.active=true;f.iconified=true;f.sync();});
  phase("hidden-running",160,()->{f.root.setVisible(false);f.sync();});
  phase("reactivated-running",220,()->{f.root.setVisible(true);f.active=true;f.iconified=false;f.sync();});
  phase("idle",160,()->{f.bar.setState(SummaryActivityBar.State.IDLE);f.card.update(SummaryActivityBar.State.IDLE,16,false);});
  phase("stopped",160,()->{f.bar.setState(SummaryActivityBar.State.STOPPED);f.card.update(SummaryActivityBar.State.STOPPED,16,false);});
  phase("inactive-docking",430,()->{f.active=false;f.bar.setState(SummaryActivityBar.State.RUNNING);f.card.update(SummaryActivityBar.State.RUNNING,16,true);f.sync();});
  edt(()->{try {
   for(int i=1;i<=10;i++){f.mockWork++;f.bar.setProgress(i*10);}
   f.active=true;f.sync();
   if(f.bar.progress()!=100||!f.bar.getAccessibleContext().getAccessibleDescription().contains("100%")||f.card.dockingFraction()!=1)throw new AssertionError("Progress/elapsed layout lost while inactive");
  }catch(Exception e){throw new RuntimeException(e);}});
  phase("background-completion",330,()->{f.active=false;f.sync();f.bar.setState(SummaryActivityBar.State.IDLE);f.card.complete(f.result,"최신 완료 결과",16);});
  edt(()->{if(!f.card.completed()||f.card.completionFraction()!=1||f.result.getParent()!=f.card)throw new AssertionError("Latest completion missing");});
  phase("active-completion-then-inactive",340,()->{f.active=true;f.bar.setState(SummaryActivityBar.State.RUNNING);f.card.update(SummaryActivityBar.State.RUNNING,16,false);f.sync();f.bar.setState(SummaryActivityBar.State.IDLE);f.card.complete(f.result,"최신 완료 결과",16);f.active=false;f.sync();});
  edt(()->{try{if(get(f.card,"outgoing")!=null)throw new AssertionError("Dormant snapshot retained past deadline");}catch(Exception e){throw new RuntimeException(e);}});
  phase("resume-completed-final",160,()->{f.active=true;f.sync();});
  edt(()->{try{javax.imageio.ImageIO.write(f.canvas,"png",out.resolve("completed-on-resume.png").toFile());}catch(Exception e){throw new RuntimeException(e);}});
  edt(()->{try {
   JPanel other=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return isVisible();}};
   other.setSize(640,420);other.addNotify();f.active=false;
   f.bar.setState(SummaryActivityBar.State.RUNNING);f.card.update(SummaryActivityBar.State.RUNNING,16,false);
   f.root.remove(f.card);other.add(f.card);other.doLayout();f.card.doLayout();
   int attached=f.bar.getHierarchyListeners().length+f.card.getHierarchyListeners().length;
   other.remove(f.card);f.root.add(f.card);f.root.doLayout();f.card.doLayout();other.removeNotify();f.sync();
   if(attached!=f.bar.getHierarchyListeners().length+f.card.getHierarchyListeners().length||f.bar.progress()!=100)throw new AssertionError("Parent swap duplicated observation or lost progress");
   f.active=true;f.sync();if(!f.barTimer.isRunning())throw new AssertionError("Reattached running UI did not restart");
   f.active=false;f.sync();
   rows.add(Map.of("phase","parent-swap","hierarchyListeners",attached,"progress",f.bar.progress(),"reattachedTimerRestarted",true));
  }catch(Exception e){throw new RuntimeException(e);}});
  phase("closed",180,()->{f.card.close();f.bar.close();});
  edt(()->{try {
   int listeners=f.bar.getHierarchyListeners().length+f.card.getHierarchyListeners().length;
   rows.add(Map.of("phase","closed-listeners","widgetHierarchyListeners",listeners,"mockUsefulWorkCompleted",f.mockWork,"lastProgress",f.bar.progress(),"accessibleName",f.card.getAccessibleContext().getAccessibleName()));
   f.root.removeNotify();f.canvas.flush();
  }catch(Exception e){throw new RuntimeException(e);}});
  edt(()->{try {
   java.util.concurrent.atomic.AtomicLong now=new java.util.concurrent.atomic.AtomicLong();Fixture sample=new Fixture(now::get);
   sample.bar.setState(SummaryActivityBar.State.IDLE);sample.card.complete(sample.result,"재활성 시점",16);
   long origin=(long)get(sample.card,"completionStarted");now.set(origin+100_000_000L);sample.active=false;sample.sync();
   now.set(origin+150_000_000L);sample.active=true;sample.sync();
   boolean gated;try{SummaryActivityBar.class.getDeclaredConstructor(LongSupplier.class,BooleanSupplier.class);gated=true;}catch(NoSuchMethodException baseline){gated=false;}
   if(gated&&(Math.abs(sample.card.completionFraction()-150d/260)>1e-12||!sample.card.motionRunning()||sample.motion.getInitialDelay()!=16||(long)get(sample.card,"completionStarted")!=origin))throw new AssertionError("Resume reset time/cadence");
   sample.card.tick();
   if(Math.abs(sample.card.completionFraction()-150d/260)>1e-12)throw new AssertionError("Elapsed transition mismatch");
   rows.add(Map.of("phase","resume-before-deadline","fraction",sample.card.completionFraction(),"originPreserved",true,"foregroundInitialDelay",sample.motion.getInitialDelay()));
   now.set(origin+SummaryOverviewLoading.COMPLETE_NANOS);sample.card.tick();sample.card.close();sample.bar.close();sample.root.removeNotify();sample.canvas.flush();
  }catch(Exception e){throw new RuntimeException(e);}});
  Files.writeString(out.resolve("metrics.json"),new GsonBuilder().setPrettyPrinting().create().toJson(Map.of("rows",rows,"windowCount",Window.getWindows().length,"nativeWindowTest",false,"facts","Showing uses real lightweight hierarchy; active/iconified facts injected. Native Window event binding inspected separately.","paint","Conservative dirty union painted into software RGB image on fixture EDT; no native compositor.","usefulWork","10 mock progress commits; no provider/process/network API")));
  try {
   SummaryActivityBar.class.getDeclaredConstructor(LongSupplier.class,BooleanSupplier.class);
   for(Map<String,Object> row:rows) {
    String phase=(String)row.get("phase");
    if(Set.of("inactive-running","iconified-running","hidden-running","idle","stopped","inactive-docking","background-completion","active-completion-then-inactive","resume-completed-final","closed").contains(phase)) {
     if(((Number)row.get("barCallbacks")).intValue()!=0||((Number)row.get("motionFrameCallbacks")).intValue()!=0||((Number)row.get("dirtyCalls")).longValue()!=0)throw new AssertionError("Unneeded decorative work: "+phase);
    }
    if(phase.equals("closed-listeners")&&((Number)row.get("widgetHierarchyListeners")).intValue()!=0)throw new AssertionError("Closed observers retained");
    if(phase.equals("active-completion-then-inactive")&&((Number)row.get("deadlineCleanupCallbacks")).intValue()>1)throw new AssertionError("Repeated dormant cleanup");
    if(phase.equals("resume-completed-final")&&((Number)row.get("inputDirtyCalls")).longValue()==0)throw new AssertionError("Final resumed pixels were not refreshed");
   }
  }catch(NoSuchMethodException baselineWithoutGate) { }
  if(Window.getWindows().length!=0)throw new AssertionError("No Window");System.out.println("Gate fixture complete; windows=0; mock work="+f.mockWork);System.exit(0);
 }
 interface Change{void run()throws Exception;}
 static void phase(String name,int millis,Change change)throws Exception {
  long[] input=new long[4];var allocation=(com.sun.management.ThreadMXBean)THREAD;
  edt(()->{try{long cpu=THREAD.getCurrentThreadCpuTime(),bytes=allocation.getThreadAllocatedBytes(edtId),dirtyBefore=f.meter.calls;change.run();input[3]=f.meter.calls-dirtyBefore;f.meter.flush();input[0]=THREAD.getCurrentThreadCpuTime()-cpu;input[1]=allocation.getThreadAllocatedBytes(edtId)-bytes;input[2]=get(f.card,"outgoing") instanceof BufferedImage image?(long)image.getWidth()*image.getHeight()*4:0;f.reset();}catch(Exception e){throw new RuntimeException(e);}});
  long cpu=OS.getProcessCpuTime(),wall=System.nanoTime(),edtCpu=THREAD.getThreadCpuTime(edtId);
  Thread.sleep(millis);edt(()->f.meter.flush());
  long process=OS.getProcessCpuTime()-cpu,elapsed=System.nanoTime()-wall,edtCost=THREAD.getThreadCpuTime(edtId)-edtCpu;
  edt(()->{try {
   Map<String,Object> row=new LinkedHashMap<>();row.put("phase",name);row.put("nominalMillis",millis);row.put("wallMs",elapsed/1e6);row.put("processCpuMs",process/1e6);row.put("edtCpuMs",edtCost/1e6);row.put("inputEdtCpuMs",input[0]/1e6);row.put("inputAllocatedBytes",input[1]);row.put("inputDirtyCalls",input[3]);row.put("outgoingBytesAtStart",input[2]);row.put("barCallbacks",f.barEvents);row.put("motionFrameCallbacks",f.motionEvents);row.put("deadlineCleanupCallbacks",f.cleanupEvents);row.put("dirtyCalls",f.meter.calls);row.put("requestedLogicalArea",f.meter.area);row.put("paintedLogicalArea",f.meter.paintedArea);row.put("paintCount",f.meter.paints);row.put("progress",f.bar.progress());row.put("dockingFraction",f.card.dockingFraction());row.put("completionFraction",f.card.completionFraction());row.put("outgoingBytes",get(f.card,"outgoing") instanceof BufferedImage image?(long)image.getWidth()*image.getHeight()*4:0);row.put("showing",f.card.isShowing());row.put("injectedWindowActive",f.active);row.put("injectedIconified",f.iconified);row.put("barTimerRunning",f.barTimer.isRunning());row.put("visualMotionRunning",f.card.motionRunning());rows.add(row);
  }catch(Exception e){throw new RuntimeException(e);}});
 }
 static final class Fixture {
  boolean active=true,iconified;int mockWork,barEvents,motionEvents,cleanupEvents;
  final BooleanSupplier gate=()->active&&!iconified;
  final JPanel root=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return isVisible();}};
  SummaryActivityBar bar;SummaryOverviewLoading card;final JPanel result=new JPanel();
  final javax.swing.Timer barTimer,motion;final BufferedImage canvas=new BufferedImage(640,420,BufferedImage.TYPE_INT_RGB);final Meter meter=new Meter();
  Fixture()throws Exception {this(System::nanoTime);}
  Fixture(LongSupplier time)throws Exception {
   try{var ctor=SummaryActivityBar.class.getDeclaredConstructor(LongSupplier.class,BooleanSupplier.class);bar=ctor.newInstance(time,gate);}catch(NoSuchMethodException baseline){bar=new SummaryActivityBar(time);}
   try{var ctor=SummaryOverviewLoading.class.getDeclaredConstructor(SummaryActivityBar.class,LongSupplier.class,BooleanSupplier.class);card=ctor.newInstance(bar,time,gate);}catch(NoSuchMethodException baseline){card=new SummaryOverviewLoading(bar,time);}
   barTimer=(javax.swing.Timer)get(bar,"timer");motion=(javax.swing.Timer)get(card,"motion");
   root.add(card);root.setSize(640,420);root.addNotify();root.doLayout();card.doLayout();
   meter.fixture=this;RepaintManager.setCurrentManager(meter);meter.setDoubleBufferingEnabled(false);
   barTimer.addActionListener(event->{barEvents++;SwingUtilities.invokeLater(meter::flush);});
   motion.addActionListener(event->{try{if(Boolean.TRUE.equals(get(card,"dormantCleanup")))cleanupEvents++;else motionEvents++;}catch(NoSuchFieldException baseline){motionEvents++;}catch(Exception e){throw new RuntimeException(e);}SwingUtilities.invokeLater(meter::flush);});
   result.add(new JLabel("유용한 작업의 최신 완료 결과"));result.setPreferredSize(new Dimension(600,110));
   bar.setState(SummaryActivityBar.State.RUNNING);bar.setProgress(37);card.update(SummaryActivityBar.State.RUNNING,16,false);meter.flush();
  }
  void sync()throws Exception{SummaryAnimationWindowTest.sync(bar);SummaryAnimationWindowTest.sync(card);}
  void reset(){barEvents=motionEvents=cleanupEvents=0;meter.reset();}
 }
 static final class Meter extends RepaintManager {
  Fixture fixture;long calls,area,paintedArea,paints;Rectangle damage;
  @Override public void addDirtyRegion(JComponent c,int x,int y,int w,int h){
   if(fixture==null||w<=0||h<=0||c!=fixture.root&&!SwingUtilities.isDescendingFrom(c,fixture.root))return;
   calls++;area+=(long)w*h;Rectangle r=SwingUtilities.convertRectangle(c,new Rectangle(x,y,w,h),fixture.root).intersection(new Rectangle(0,0,640,420));if(!r.isEmpty())damage=damage==null?r:damage.union(r);
  }
  void flush(){if(damage==null)return;Rectangle clip=damage;damage=null;Graphics2D g=fixture.canvas.createGraphics();try{g.clip(clip);fixture.root.printAll(g);}finally{g.dispose();}paintedArea+=(long)clip.width*clip.height;paints++;}
  void reset(){calls=area=paintedArea=paints=0;damage=null;}
 }
}
