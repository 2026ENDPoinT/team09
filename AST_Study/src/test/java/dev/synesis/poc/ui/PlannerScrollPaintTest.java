package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import static dev.synesis.poc.planner.PlannerModel.*;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.lang.management.ManagementFactory;
import java.util.*;
import java.util.List;

/** Same offscreen scene runs against before/after classes, without a native app or user data. */
public final class PlannerScrollPaintTest {
    static Path output;static boolean baseline;static int images;static long differing;
    public static void main(String[] args)throws Exception{
        output=Path.of(args[0]);baseline=Arrays.asList(args).contains("--baseline");Files.createDirectories(output);
        SwingUtilities.invokeAndWait(()->{try{for(double scale:new double[]{1,2,1.25})scene(scale);}catch(Exception e){throw new RuntimeException(e);}});
        if(differing!=0)throw new AssertionError(differing+" changed pixels across "+images+" scenes");
        System.out.println("PlannerScrollPaintTest: "+images+" scenes within 1/255 compositing tolerance");System.exit(0);
    }
    static void scene(double scale)throws Exception{
        LocalDate date=LocalDate.of(2026,11,2);Clock clock=Clock.fixed(date.atTime(12,0).toInstant(ZoneOffset.ofHours(9)),ZoneId.of("Asia/Seoul"));
        PlannerDesign p=new PlannerDesign(new PlannerStore(Files.createTempDirectory("planner-scroll-scene-").resolve("planner.json")),clock);
        try{
            List<PlannerModel.Event> events=new ArrayList<>();List<Task> tasks=new ArrayList<>();List<WeeklyTask> weekly=new ArrayList<>();List<MonthlyTask> monthly=new ArrayList<>();
            for(int d=0;d<7;d++)for(int i=0;i<16;i++)events.add(new PlannerModel.Event("e"+d+"-"+i,"수업 일정 "+i,"",date.plusDays(d).atTime(i+1,0),date.plusDays(d).atTime(i+2,0),false,EventColor.values()[i%EventColor.values().length],List.of("tag"),false,Repeat.NONE,-1));
            for(int i=0;i<8;i++)events.add(new PlannerModel.Event("span"+i,"연속 일정 "+i,"",date.atStartOfDay(),date.plusDays(7).atStartOfDay(),true,EventColor.BLUE,List.of(),false,Repeat.NONE,-1));
            for(int i=0;i<40;i++){
                tasks.add(new Task("d"+i,"오늘의 할 일 "+i,date,"",i%3==0));weekly.add(new WeeklyTask("w"+i,"이번 주 할 일 "+i,date,date,List.of("tag"),i%3==0));monthly.add(new MonthlyTask("m"+i,"이번 달 할 일 "+i,date.plusDays(i),date,List.of("tag"),i%3==0));
                events.add(new PlannerModel.Event("important"+i,"중요 일정 "+i,"",date.plusDays(i+1).atTime(10,0),date.plusDays(i+1).atTime(11,0),false,EventColor.TEAL,List.of(),true,Repeat.NONE,-1));
            }
            p.accept(new State(1,events,List.of(new Tag("tag","수업")),tasks,List.of(),false,Set.of(),weekly,List.of(new Tag("tag","공부")),List.of(),monthly));p.setSize(1430,950);layout(p);
            PlannerCalendar.Week week=(PlannerCalendar.Week)((PlannerCalendar)p.calendar.getComponent(0)).getComponent(0);
            for(int y:new int[]{0,7,29,140,250,245,500,0}){week.timeline.getViewport().setViewPosition(new Point(0,y));check(p,"week-"+scale+"-"+y,scale);}
            for(int y:new int[]{0,3,15,48,100,0}){week.spans.getViewport().setViewPosition(new Point(0,y));check(p,"spans-"+scale+"-"+y,scale);}
            BufferedImage image=new BufferedImage((int)Math.ceil(p.getWidth()*scale),(int)Math.ceil(p.getHeight()*scale),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.scale(scale,scale);g.setClip(SwingUtilities.convertRectangle(week.getParent(),week.getBounds(),p));
            for(int i=0;i<24;i++){week.timeline.getViewport().setViewPosition(new Point(0,100+i*4));p.paint(g);}
            long start=ManagementFactory.getThreadMXBean().getCurrentThreadCpuTime();
            for(int i=0;i<80;i++){week.timeline.getViewport().setViewPosition(new Point(0,200+(i%40)*4));p.paint(g);}
            System.out.printf(Locale.ROOT,"weekly scroll scale %.2f EDT CPU %.3f ms/frame%n",scale,(ManagementFactory.getThreadMXBean().getCurrentThreadCpuTime()-start)/80e6);g.dispose();
            p.setMonthly(true);p.setSize(1430,950);layout(p);check(p,"month-"+scale,scale);
            check(p,"month-partial-"+scale,scale,new Rectangle(28,420,1064,19));
            for(int y:new int[]{10,27,90,140,20}){
                for(JScrollPane pane:List.of(p.monthlyView.dailyScroll,p.monthlyView.todoScroll,p.monthlyView.upcomingScroll,p.monthlyView.selectedScroll))pane.getVerticalScrollBar().setValue(y);
                check(p,"month-scroll-"+scale+"-"+y,scale);
            }
            p.monthlyView.selectDate(date.plusDays(2));layout(p);check(p,"selected-"+scale,scale);
            FadeScrollPane outer=new FadeScrollPane(p);outer.setBorder(null);outer.setVerticalOverflowShadow(true);
            try{FadeScrollPane.class.getMethod("setScrollCacheEnabled",boolean.class).invoke(outer,true);}catch(NoSuchMethodException ignored){}
            outer.setSize(900,620);layout(outer);
            for(int y:new int[]{0,5,30,110,240,460,20}){outer.getVerticalScrollBar().setValue(y);check(outer,"outer-"+scale+"-"+y,scale);}
        }finally{p.dispose();}
    }
    static void check(JComponent c,String name,double scale)throws Exception{
        check(c,name,scale,null);
    }
    static void check(JComponent c,String name,double scale,Rectangle clip)throws Exception{
        BufferedImage image=new BufferedImage((int)Math.ceil(c.getWidth()*scale),(int)Math.ceil(c.getHeight()*scale),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.scale(scale,scale);g.setClip(clip==null?new Rectangle(0,0,c.getWidth(),c.getHeight()):clip);c.paint(g);g.dispose();Path path=output.resolve(name+".png");images++;
        if(baseline){ImageIO.write(image,"png",path.toFile());return;}
        BufferedImage before=ImageIO.read(path.toFile());long count=0;int max=0;
        for(int y=0;y<image.getHeight();y++)for(int x=0;x<image.getWidth();x++){int a=image.getRGB(x,y),b=before.getRGB(x,y);if(a!=b){count++;for(int s=0;s<24;s+=8)max=Math.max(max,Math.abs((a>>s&255)-(b>>s&255)));}}
        if(count>0){if(max>1)differing+=count;System.out.println(name+": "+count+" pixels differ, max "+max);if(max>1)ImageIO.write(image,"png",output.resolve(name+"-actual.png").toFile());}
    }
    static void layout(Container c){for(int i=0;i<4;i++)layoutOnce(c);}
    static void layoutOnce(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container box)layoutOnce(box);}
}
