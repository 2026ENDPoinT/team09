package dev.synesis.poc.pdf;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicLong;

/** Deterministic motion, real activity pixels and lifecycle; no window or API. */
public final class SummaryOverviewLoadingTest {
 static final Path OUT=Path.of("build/pdf-overview-completion-20261021/card");
 static void check(boolean ok,String why){if(!ok)throw new AssertionError(why);}
 static void frame(SummaryOverviewLoading card,String file)throws Exception{
  BufferedImage img=new BufferedImage(card.getWidth()*2,card.getHeight()*2,BufferedImage.TYPE_INT_RGB);
  Graphics2D g=img.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,img.getWidth(),img.getHeight());g.scale(2,2);card.printAll(g);g.dispose();ImageIO.write(img,"png",OUT.resolve(file).toFile());
 }
 public static void main(String[]args)throws Exception{
  SwingUtilities.invokeAndWait(()->{try{
   Files.createDirectories(OUT);AtomicLong now=new AtomicLong();SummaryActivityBar bar=new SummaryActivityBar(now::get);SummaryOverviewLoading card=new SummaryOverviewLoading(bar,now::get);
   bar.setState(SummaryActivityBar.State.RUNNING);bar.setProgress(37);card.update(SummaryActivityBar.State.RUNNING,16,false);
   card.setSize(640,1);int height=card.getPreferredSize().height;card.setSize(640,height);card.doLayout();Rectangle initial=bar.getBounds();
   check(initial.width==320&&initial.height==20,"expanded strips must be modest and inside the card");frame(card,"preparing-card.png");
   card.update(SummaryActivityBar.State.RUNNING,16,true);check(card.hasSummary(),"first summary must trigger docking");
   check(bar.getBounds().equals(initial),"the first animation frame must not jump");
   now.set(SummaryOverviewLoading.DOCK_NANOS/2);card.tick();Rectangle middle=bar.getBounds();
   check(middle.x>initial.x&&middle.y>initial.y&&middle.width<initial.width&&middle.height<initial.height,"strips should move down/right and shrink");
   check(card.getPreferredSize().height==height,"docking must not move or shrink the overview card");frame(card,"docking-card.png");
   card.update(SummaryActivityBar.State.RUNNING,16,true);check(card.dockingFraction()==.5,"later unit renders must not restart the animation");
   now.set(SummaryOverviewLoading.DOCK_NANOS);card.tick();Rectangle docked=bar.getBounds();
   check(docked.width==112&&docked.height==12&&docked.x+docked.width==card.getWidth()-44,"small strips must dock to the right inset");
   check(docked.y==card.getHeight()-34,"small strips must dock near the bottom");check(bar.progress()==37,"motion must preserve real progress");frame(card,"docked-card.png");
   JPanel roadmap=new JPanel();roadmap.setOpaque(false);roadmap.setPreferredSize(new Dimension(600,220));
   roadmap.add(new JLabel("생성된 강의의 흐름 · 근거 p.1"));
   card.showProgress(roadmap,"이 강의의 흐름",16,SummaryActivityBar.State.RUNNING);
   card.setSize(640,card.getPreferredSize().height);card.doLayout();
   check(roadmap.isVisible()&&!card.completed()&&bar.isVisible(),"early overview must retain the running card");
   JLabel hint=null;for(Component child:card.getComponents())if(child instanceof JLabel label&&label.getText()!=null&&label.getText().contains("AI멘토"))hint=label;
   check(hint!=null&&hint.isVisible()&&hint.getY()>=roadmap.getY()+roadmap.getHeight(),"tutor hint must follow the generated overview");
   check(bar.getY()>=hint.getY()+hint.getHeight()&&bar.getY()==card.getHeight()-34,"live roadmap overlapped bottom-right loading bar");
   check(bar.progress()==37&&card.dockingFraction()==1,"early overview restarted activity or reset progress");
   frame(card,"live-overview-card.png");
   bar.setState(SummaryActivityBar.State.STOPPED);card.update(SummaryActivityBar.State.STOPPED,16,true);check(!card.motionRunning(),"stop should stop movement");frame(card,"stopped-card.png");
   bar.setState(SummaryActivityBar.State.RUNNING);card.update(SummaryActivityBar.State.RUNNING,16,false);card.doLayout();check(!card.hasSummary()&&bar.getBounds().equals(initial),"retry must restore expanded loading");
   card.setSize(300,1);card.setSize(300,card.getPreferredSize().height);card.doLayout();frame(card,"narrow-card.png");check(bar.getX()>=24&&bar.getX()+bar.getWidth()<=276,"narrow loading must stay in its card");
   for(Component child:card.getComponents())if(child instanceof JLabel label) {
    Object view=label.getClientProperty(javax.swing.plaf.basic.BasicHTML.propertyKey);
    if(view instanceof javax.swing.text.View html)check(html.getPreferredSpan(javax.swing.text.View.X_AXIS)<=label.getWidth()+1,"narrow helper text clipped");
   }
   card.setSize(640,height);card.doLayout();card.addNotify();
   check(card.isShowing(),"headless display lifecycle not attached");
   JPanel result=new JPanel();result.setOpaque(false);result.add(new JLabel("실제 강의 흐름 · 근거 p.2"));result.setPreferredSize(new Dimension(600,100));
   card.complete(result,"이 강의의 흐름",16);card.setSize(640,card.getPreferredSize().height);card.doLayout();
   check(card.completed()&&!bar.isVisible(),"completion must hide the loading bar");
   check(card.completionFraction()==0&&card.motionRunning(),"visible completion must animate locally");
   int completionHeight=card.getPreferredSize().height;frame(card,"completion-start.png");
   long start=now.get();now.set(start+SummaryOverviewLoading.COMPLETE_NANOS/2);card.tick();
   check(card.completionFraction()==.5,"completion transition did not advance");frame(card,"completion-middle.png");
   card.complete(result,"이 강의의 흐름",16);check(card.completionFraction()==.5,"rerender restarted completion");
   now.set(start+SummaryOverviewLoading.COMPLETE_NANOS);card.tick();
   check(card.completionFraction()==1&&!card.motionRunning(),"completion timer did not stop");
   check(card.getPreferredSize().height==completionHeight,"completion shifted the reading position");
   card.setSize(640,card.getPreferredSize().height);card.doLayout();frame(card,"completed.png");
   card.update(SummaryActivityBar.State.RUNNING,16,false);
   check(!card.completed()&&bar.isVisible()&&!result.isVisible(),"new run did not reset completed state");
   card.removeNotify();
   card.close();bar.close();check(!card.motionRunning(),"closing should stop motion");
   System.out.println("PASS: overview placeholder, local 380ms docking, stable layout, repeated results, progress, stop/retry and narrow viewport");
  }catch(Exception e){throw new RuntimeException(e);}});
 }
}
