package dev.synesis.poc.pdf;
import java.awt.*;
import java.awt.image.*;
import java.lang.management.*;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.function.*;
import javax.swing.*;
import com.google.gson.*;

/** Standalone real private CreateButton; no QuizPanel instance, click, provider or Window. */
public final class QuizCreateButtonActivityTest {
 static final Class<?> TYPE=type();static final ThreadMXBean THREAD=ManagementFactory.getThreadMXBean();
 static final com.sun.management.OperatingSystemMXBean OS=(com.sun.management.OperatingSystemMXBean)ManagementFactory.getOperatingSystemMXBean();
 static final List<Map<String,Object>> rows=new ArrayList<>();static Fixture f;static long edtId;
 static Class<?> type(){try{return Class.forName("dev.synesis.poc.pdf.QuizPanel$CreateButton");}catch(Exception e){throw new RuntimeException(e);}}
 static Object get(Object object,String name)throws Exception{Field field=TYPE.getDeclaredField(name);field.setAccessible(true);return field.get(object);}
 static Object call(Object object,String name,Class<?>[] types,Object...args)throws Exception{Method method=TYPE.getDeclaredMethod(name,types);method.setAccessible(true);return method.invoke(object,args);}
 static void edt(Runnable action)throws Exception{SwingUtilities.invokeAndWait(action);}
 static boolean candidate(){try{TYPE.getDeclaredMethod("syncMotion");return true;}catch(Exception e){return false;}}
 public static void main(String[] args)throws Exception {
  Path out=Path.of(args[0]);Files.createDirectories(out);
  edt(()->{try{edtId=Thread.currentThread().threadId();f=new Fixture(System::nanoTime);}catch(Exception e){throw new RuntimeException(e);}});
  Thread.sleep(180);
  phase("active-generating",240,()->{});
  phase("inactive-generating",240,()->{f.active=false;f.sync();});
  phase("iconified-generating",240,()->{f.active=true;f.iconified=true;f.sync();});
  phase("hidden-generating",180,()->{f.root.setVisible(false);f.sync();});
  phase("shown-inactive",220,()->{f.root.setVisible(true);f.active=false;f.iconified=false;f.sync();});
  edt(()->{try{for(int i=1;i<=10;i++){f.mockWork++;f.button.setText("문제집 생성 중 · "+i*10+"%");f.progress(true,i*10);}if((int)get(f.button,"progress")!=100||!f.button.getAccessibleContext().getAccessibleDescription().contains("100"))throw new AssertionError("Useful progress lost");}catch(Exception e){throw new RuntimeException(e);}});
  phase("reactivated-generating",220,()->{f.active=true;f.sync();});
  phase("inactive-hover-model",230,()->{f.active=false;f.sync();f.progress(false,100);f.button.setEnabled(true);f.button.getModel().setRollover(true);});
  phase("reactivated-idle-hover",160,()->{f.active=true;f.sync();});
  edt(()->{try{if(Math.abs((double)get(f.button,"hover")-1)>1e-12)throw new AssertionError("Hover did not catch up");}catch(Exception e){throw new RuntimeException(e);}});
  phase("active-hover-exit",220,()->f.button.getModel().setRollover(false));
  phase("inactive-error-disabled",180,()->{f.active=false;f.sync();f.button.setEnabled(false);f.button.setText("다시 시도");f.progress(false,45);});
  phase("inactive-completed",180,()->{f.button.setText("생성 완료 · 100%");f.progress(false,100);});
  phase("reduce-motion-generating",180,()->{System.setProperty("synesis.reduceMotion","true");f.active=true;f.sync();f.progress(true,100);});
  phase("explicit-dispose",180,()->{System.clearProperty("synesis.reduceMotion");f.sync();f.dispose();f.button.setText("문제집 생성 중 · 61%");f.progress(true,61);});
  edt(()->{try {
   f.root.remove(f.button);f.root.add(f.button);f.root.doLayout();f.sync();
   if(!f.motion.isRunning()||f.motion.getDelay()!=33||(int)get(f.button,"progress")!=61)throw new AssertionError("Reattach did not restore generating state");
   int count=f.button.getHierarchyListeners().length;
   JPanel other=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return isVisible();}};other.setSize(320,58);other.addNotify();
   f.active=false;f.root.remove(f.button);other.add(f.button);other.doLayout();other.remove(f.button);f.root.add(f.button);f.root.doLayout();other.removeNotify();f.sync();
   if(f.button.getHierarchyListeners().length!=count)throw new AssertionError("Duplicate parent observation");
   rows.add(Map.of("phase","reattach-parent","hierarchyListeners",count,"progress",get(f.button,"progress"),"generating",get(f.button,"generating"),"timerWhileInactive",f.motion.isRunning()));
   f.button.setText("생성 완료 · 100%");f.progress(false,100);
  }catch(Exception e){throw new RuntimeException(e);}});
  phase("detached",180,()->f.root.remove(f.button));
  edt(()->{try {
   rows.add(Map.of("phase","final","actionsInvoked",f.actions,"mockWorkCompleted",f.mockWork,"progress",get(f.button,"progress"),"hierarchyListeners",f.button.getHierarchyListeners().length,"actionKeys",Arrays.toString(f.button.getActionMap().allKeys()),"inputKeys",Arrays.toString(f.button.getInputMap(JComponent.WHEN_FOCUSED).allKeys()),"accessible",f.button.getAccessibleContext().getAccessibleDescription()));
   f.root.removeNotify();f.canvas.flush();
  }catch(Exception e){throw new RuntimeException(e);}});
  if(candidate())edt(()->{try {
   java.util.concurrent.atomic.AtomicLong now=new java.util.concurrent.atomic.AtomicLong();Fixture sample=new Fixture(now::get);
   sample.progress(false,100);sample.button.setEnabled(true);sample.button.getModel().setRollover(true);
   long origin=(long)get(sample.button,"started");sample.active=false;sample.sync();now.set(origin+90_000_000L);sample.active=true;sample.sync();
   if(Math.abs((double)get(sample.button,"hover")-.875)>1e-12||(long)get(sample.button,"started")!=origin||sample.motion.getDelay()!=16)throw new AssertionError("Hover resume reset its elapsed time/cadence");
   sample.active=false;sample.sync();now.set(origin+130_000_000L);sample.button.getModel().setRollover(false);
   double from=1-Math.pow(1-130d/180,3);now.set(origin+220_000_000L);sample.active=true;sample.sync();
   if(Math.abs((double)get(sample.button,"hover")-from*.125)>1e-12||(long)get(sample.button,"started")!=origin+130_000_000L)throw new AssertionError("Inactive model retarget lost absolute time");
   rows.add(Map.of("phase","elapsed-hover-resume","firstFraction",.875,"retargetedFraction",get(sample.button,"hover"),"originPreserved",true,"hoverDelay",sample.motion.getDelay()));
   sample.dispose();sample.root.removeNotify();sample.canvas.flush();
  }catch(Exception e){throw new RuntimeException(e);}});
  if(candidate())for(Map<String,Object> row:rows) {
   String name=(String)row.get("phase");
   if(Set.of("inactive-generating","iconified-generating","hidden-generating","shown-inactive","inactive-hover-model","reactivated-idle-hover","inactive-error-disabled","inactive-completed","reduce-motion-generating","explicit-dispose","detached").contains(name))if(((Number)row.get("callbacks")).intValue()!=0||((Number)row.get("dirtyCalls")).intValue()!=0)throw new AssertionError("Decorative work while stopped: "+name);
   if(name.equals("final")&&((Number)row.get("hierarchyListeners")).intValue()!=0)throw new AssertionError("Detached observer retained");
  }
  if(f.actions!=0||Window.getWindows().length!=0)throw new AssertionError("No action/Window allowed");
  Files.writeString(out.resolve("metrics.json"),new GsonBuilder().setPrettyPrinting().create().toJson(Map.of("rows",rows,"windowCount",0,"actualQuizPanelConstructed",false,"facts","active/iconified injected; showing/removal/reattachment are real lightweight hierarchy. Native Window delivery/focus/keyboard not tested.","paidApiCalls",0)));
  System.out.println("PASS: actual CreateButton, no action/provider/Window; mock commits="+f.mockWork);System.exit(0);
 }
 interface Change{void run()throws Exception;}
 static void phase(String name,int duration,Change change)throws Exception {
  long[] input=new long[2];
  edt(()->{try{long before=f.meter.calls;change.run();input[0]=f.meter.calls-before;f.meter.flush();f.reset();}catch(Exception e){throw new RuntimeException(e);}});
  long cpu=OS.getProcessCpuTime(),wall=System.nanoTime(),edt=THREAD.getThreadCpuTime(edtId);Thread.sleep(duration);edt(()->f.meter.flush());
  long process=OS.getProcessCpuTime()-cpu,elapsed=System.nanoTime()-wall,edtCpu=THREAD.getThreadCpuTime(edtId)-edt;
  edt(()->{try{Map<String,Object> row=new LinkedHashMap<>();row.put("phase",name);row.put("durationMs",duration);row.put("wallMs",elapsed/1e6);row.put("processCpuMs",process/1e6);row.put("edtCpuMs",edtCpu/1e6);row.put("inputDirtyCalls",input[0]);row.put("callbacks",f.events);row.put("dirtyCalls",f.meter.calls);row.put("requestedArea",f.meter.area);row.put("paintedArea",f.meter.paintedArea);row.put("paintCount",f.meter.paints);row.put("timerDelay",f.motion.getDelay());row.put("timerRunning",f.motion.isRunning());row.put("generating",get(f.button,"generating"));row.put("progress",get(f.button,"progress"));row.put("hover",get(f.button,"hover"));row.put("target",get(f.button,"target"));row.put("activeFact",f.active);row.put("iconifiedFact",f.iconified);row.put("showing",f.button.isShowing());rows.add(row);}catch(Exception e){throw new RuntimeException(e);}});
 }
 static final class Fixture {
  boolean active=true,iconified;int events,actions,mockWork;JButton button;final javax.swing.Timer motion;
  final JPanel root=new JPanel(new BorderLayout()){@Override public boolean isShowing(){return isVisible();}};
  final BufferedImage canvas=new BufferedImage(320,58,BufferedImage.TYPE_INT_RGB);final Meter meter=new Meter();
  Fixture(LongSupplier time)throws Exception {
   Constructor<?> ctor;
   try{ctor=TYPE.getDeclaredConstructor(LongSupplier.class,BooleanSupplier.class);ctor.setAccessible(true);button=(JButton)ctor.newInstance(time,(BooleanSupplier)()->active&&!iconified);}catch(NoSuchMethodException baseline){ctor=TYPE.getDeclaredConstructor();ctor.setAccessible(true);button=(JButton)ctor.newInstance();}
   button.addActionListener(e->{actions++;throw new AssertionError("No button action may be invoked");});motion=(javax.swing.Timer)get(button,"motion");
   root.add(button);root.setSize(320,58);root.addNotify();root.doLayout();
   meter.fixture=this;RepaintManager.setCurrentManager(meter);meter.setDoubleBufferingEnabled(false);motion.addActionListener(e->{events++;SwingUtilities.invokeLater(meter::flush);});
   button.setEnabled(false);button.setText("문제집 생성 중 · 35%");progress(true,35);meter.flush();
  }
  void progress(boolean running,int percent)throws Exception{call(button,"setProgress",new Class<?>[]{boolean.class,int.class},running,percent);}
  void sync()throws Exception{call(button,candidate()?"syncMotion":"updateMotion",new Class<?>[0]);}
  void dispose()throws Exception{if(candidate())call(button,"disposeAnimation",new Class<?>[0]);else button.removeNotify();}
  void reset(){events=0;meter.calls=meter.area=meter.paintedArea=meter.paints=0;meter.damage=null;}
 }
 static final class Meter extends RepaintManager {
  Fixture fixture;long calls,area,paintedArea,paints;Rectangle damage;
  @Override public void addDirtyRegion(JComponent component,int x,int y,int w,int h){if(fixture==null||w<=0||h<=0||component!=fixture.root&&!SwingUtilities.isDescendingFrom(component,fixture.root))return;calls++;area+=(long)w*h;Rectangle r=SwingUtilities.convertRectangle(component,new Rectangle(x,y,w,h),fixture.root).intersection(new Rectangle(0,0,320,58));if(!r.isEmpty())damage=damage==null?r:damage.union(r);}
  void flush(){if(damage==null)return;Rectangle clip=damage;damage=null;Graphics2D g=fixture.canvas.createGraphics();try{g.clip(clip);fixture.root.printAll(g);}finally{g.dispose();}paintedArea+=(long)clip.width*clip.height;paints++;}
 }
}
