package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import dev.synesis.poc.ui.AnimationWindow;

import dev.synesis.poc.ui.StudyTheme;
import java.awt.*;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import java.util.function.LongSupplier;
import java.util.function.BooleanSupplier;
import javax.swing.*;
import javax.swing.plaf.basic.BasicHTML;
import javax.swing.text.View;

/** One overview card for preparation, live progress and the completed rich content. */
final class SummaryOverviewLoading extends JPanel implements AutoCloseable {
    static final long DOCK_NANOS=380_000_000L;
    static final long COMPLETE_NANOS=260_000_000L;
    private final SummaryActivityBar activity;
    private final LongSupplier clock;
    private final JLabel title=new JLabel("이 강의의 흐름");
    private final JLabel description=new JLabel(),tutor=new JLabel();
    private final Timer motion=new Timer(16,e->onTimer());
    private final BooleanSupplier windowActive;
    private final Runnable stopObserving;
    private boolean animationWasActive,dormantCleanup,dormantDirty;
    private SummaryActivityBar.State state=SummaryActivityBar.State.IDLE;
    private int fontSize=-1,textWidth=-1;
    private boolean compact,closed,completed,loadingShown,liveContent;
    private JComponent result;
    private BufferedImage outgoing;
    private long completionStarted;
    private double completionFraction=1;
    private long dockingStarted;
    private double fraction;
    private String descriptionText="";
    private static final String TUTOR="강의 해설 생성 중에도 PDF와 연결된 AI멘토를 이용할 수 있어요.";

    SummaryOverviewLoading(SummaryActivityBar activity){this(activity,System::nanoTime);}
    SummaryOverviewLoading(SummaryActivityBar activity,LongSupplier clock) {
        this(activity,clock,null);
    }
    SummaryOverviewLoading(SummaryActivityBar activity,LongSupplier clock,BooleanSupplier windowActive) {
        super(null);this.activity=activity;this.clock=clock;
        this.windowActive=windowActive==null?()->AnimationWindow.active(this):windowActive;
        setOpaque(false);activity.setFitToBounds(true);
        title.setForeground(Color.BLACK);description.setForeground(Color.BLACK);
        tutor.setForeground(Color.BLACK);
        add(title);add(description);add(tutor);add(activity);
        motion.setCoalesce(true);
        stopObserving=AnimationWindow.watch(this,this::syncTimer);
        getAccessibleContext().setAccessibleName("이 강의의 흐름 · 강의 해설 생성 진행 상태");
    }

    void update(SummaryActivityBar.State next,int font,boolean hasSummary) {
        if(next!=state) {
            if(next==SummaryActivityBar.State.RUNNING){
                compact=false;fraction=0;motion.stop();completed=false;liveContent=false;releaseOutgoing();completionFraction=1;
                loadingShown=true;title.setText("이 강의의 흐름");
                if(result!=null)result.setVisible(false);
                description.setVisible(true);tutor.setVisible(true);activity.setVisible(true);
            }
            state=next;
            if(next!=SummaryActivityBar.State.RUNNING)motion.stop();
        }
        if(fontSize!=font) {
            fontSize=font;textWidth=-1;
            title.setFont(StudyTheme.font(Font.BOLD,Math.max(12,Math.round(font*1.4f))));
            description.setFont(StudyTheme.font(Font.PLAIN,Math.max(11,Math.round(font*1.2f))));
            tutor.setFont(StudyTheme.font(Font.PLAIN,Math.max(10,Math.round(font*.95f))));
            revalidate();
        }
        String copy=next==SummaryActivityBar.State.STOPPED
            ?"강의 해설 생성이 중단됐어요. 완료된 내용은 보관했어요."
            :"강의의 흐름을 PDF를 읽으며 정리하고 있어요.";
        if(!copy.equals(descriptionText)){descriptionText=copy;textWidth=-1;revalidate();}
        if(hasSummary&&!compact) {
            compact=true;dockingStarted=clock.getAsLong();
            syncTimer();
        }
        if(next!=SummaryActivityBar.State.RUNNING&&compact)fraction=1;
        syncTimer();doLayout();repaint();
    }

    /** Keep the generated roadmap inside the active card until teaching finishes. */
    void showProgress(JComponent content,String heading,int font,SummaryActivityBar.State next) {
        update(next,font,true);
        completed=false;liveContent=true;
        title.setText(heading);description.setVisible(false);tutor.setVisible(true);activity.setVisible(true);
        if(result!=content) {
            if(result!=null)remove(result);
            result=content;add(content);
        }
        result.setVisible(true);
        revalidate();doLayout();repaint();
    }
    void clearProgressContent() {
        liveContent=false;
        if(result!=null)result.setVisible(false);
        description.setVisible(true);tutor.setVisible(true);activity.setVisible(true);
    }

    void complete(JComponent content,String heading,int font) {
        update(SummaryActivityBar.State.IDLE,font,false);
        if(!completed) {
            boolean animate=loadingShown && isShowing() && windowActive.getAsBoolean() && getWidth()>0 && getHeight()>0;
            if(animate) {
                outgoing=new BufferedImage(getWidth(),getHeight(),BufferedImage.TYPE_INT_ARGB);
                Graphics2D g=outgoing.createGraphics();
                for(Component child:new Component[]{description,tutor,activity})paintChild(g,child,1);
                if(result!=null)paintChild(g,result,1);
                g.dispose();
            }
            completed=true;loadingShown=false;completionFraction=animate?0:1;
            completionStarted=clock.getAsLong();
        }
        liveContent=false;
        title.setText(heading);description.setVisible(false);tutor.setVisible(false);activity.setVisible(false);
        if(result!=content) {
            if(result!=null)remove(result);
            result=content;add(content);
        }
        result.setVisible(true);
        getAccessibleContext().setAccessibleName(heading);
        syncTimer();revalidate();doLayout();repaint();
    }
    boolean completed(){return completed;}
    double completionFraction(){return completionFraction;}
    boolean hasSummary(){return compact;}
    double dockingFraction(){return fraction;}
    boolean motionRunning(){return motion.isRunning()&&!dormantCleanup;}

    private void wrap() {
        int width=Math.max(80,getWidth()-88);
        if(width==textWidth)return;
        textWidth=width;
        description.setText("<html>"+descriptionText+"</html>");
        tutor.setText("<html>"+TUTOR+"</html>");
        // Set the HTML view's logical width directly. CSS px would be scaled
        // by Swing and could clip Korean text in a narrow reading column.
        for(JLabel label:new JLabel[]{description,tutor}) {
            View view=(View)label.getClientProperty(BasicHTML.propertyKey);
            if(view!=null)view.setSize(width,0);
        }
    }
    private int resultY(){return 32+title.getPreferredSize().height+12;}
    private int resultHeight(){
        if(result==null)return 0;
        result.setSize(Math.max(1,getWidth()-40),Math.max(1,result.getHeight()));
        return result.getPreferredSize().height;
    }
    private int barY(){return liveContent?hintY()+tutor.getPreferredSize().height+12
        :32+title.getPreferredSize().height+24+description.getPreferredSize().height+14;}
    private int hintY(){return liveContent?resultY()+resultHeight()+14:barY()+30;}
    @Override public Dimension getPreferredSize(){
        wrap();
        if(completed && result!=null) {
            result.setSize(Math.max(1,getWidth()-40),Math.max(1,result.getHeight()));
            // Measure the wrapped evidence at the current column width. The
            // completed card follows its content, not the former loading height.
            return new Dimension(640,resultY()+resultHeight()+16);
        }
        return new Dimension(640,hintY()+tutor.getPreferredSize().height+(liveContent?58:52));
    }
    @Override public void doLayout() {
        wrap();int width=Math.max(1,getWidth()-88);
        title.setBounds(44,32,width,title.getPreferredSize().height);
        if(completed && result!=null) {
            result.setBounds(20,resultY(),Math.max(1,getWidth()-40),resultHeight());
            result.doLayout();return;
        }
        if(liveContent && result!=null) {
            result.setBounds(20,resultY(),Math.max(1,getWidth()-40),resultHeight());
            result.doLayout();
        } else description.setBounds(44,32+title.getHeight()+24,width,description.getPreferredSize().height);
        tutor.setBounds(44,hintY(),width,tutor.getPreferredSize().height);
        placeActivity();
    }
    private void placeActivity() {
        int available=Math.max(1,getWidth()-88);
        int wide=Math.min(320,available),small=Math.min(112,available);
        double eased=1-Math.pow(1-fraction,3);
        int x=(int)Math.round(44+(getWidth()-44-small-44)*eased);
        int y=(int)Math.round(barY()+(Math.max(barY(),getHeight()-34)-barY())*eased);
        int width=(int)Math.round(wide+(small-wide)*eased),height=(int)Math.round(20-8*eased);
        activity.setBounds(x,y,width,height);
    }
    void tick() {
        if(completed) {
            if(closed){motion.stop();return;}
            completionFraction=Math.min(1,Math.max(0,(clock.getAsLong()-completionStarted)/(double)COMPLETE_NANOS));
            repaint();
            if(completionFraction>=1){releaseOutgoing();motion.stop();revalidate();}
            return;
        }
        if(!compact||closed||state!=SummaryActivityBar.State.RUNNING){motion.stop();return;}
        fraction=Math.min(1,Math.max(0,(clock.getAsLong()-dockingStarted)/(double)DOCK_NANOS));
        Rectangle before=activity.getBounds();placeActivity();Rectangle after=activity.getBounds();
        repaint(before.union(after));
        if(fraction>=1)motion.stop();
    }
    private void syncTimer(){
        if(closed){motion.stop();dormantCleanup=false;return;}
        boolean active=isShowing()&&windowActive.getAsBoolean();
        boolean resumed=active&&!animationWasActive;animationWasActive=active;
        if(!active) {
            motion.stop();dormantCleanup=false;settleElapsed(false);
            // No decorative frames while inactive. One deadline callback releases an existing
            // completion snapshot even if this component never becomes visible again.
            if(completed&&outgoing!=null&&completionFraction<1) {
                long remaining=COMPLETE_NANOS-(clock.getAsLong()-completionStarted);
                int delay=(int)Math.max(1,Math.ceil(remaining/1_000_000.0));
                dormantCleanup=true;motion.setRepeats(false);motion.setInitialDelay(delay);motion.start();
            }
            return;
        }
        if(resumed) {
            settleElapsed(true);
            if(dormantDirty){dormantDirty=false;revalidate();doLayout();repaint();}
        }
        boolean moving=completed?completionFraction<1:compact&&fraction<1&&state==SummaryActivityBar.State.RUNNING;
        if(dormantCleanup){motion.stop();dormantCleanup=false;}
        motion.setRepeats(true);motion.setInitialDelay(16);
        if(moving)motion.start();else motion.stop();
    }
    private void onTimer() {
        if(closed){motion.stop();return;}
        if(dormantCleanup||!isShowing()||!windowActive.getAsBoolean()){syncTimer();return;}
        tick();
    }
    private void settleElapsed(boolean visible) {
        if(completed&&completionFraction<1) {
            double previous=completionFraction;
            completionFraction=Math.min(1,Math.max(0,(clock.getAsLong()-completionStarted)/(double)COMPLETE_NANOS));
            if(completionFraction>=1)releaseOutgoing();
            if(previous!=completionFraction) {
                if(visible){revalidate();doLayout();repaint();}else dormantDirty=true;
            }
        } else if(compact&&fraction<1&&state==SummaryActivityBar.State.RUNNING) {
            double previous=fraction;
            fraction=Math.min(1,Math.max(0,(clock.getAsLong()-dockingStarted)/(double)DOCK_NANOS));
            Rectangle before=activity.getBounds();placeActivity();
            if(visible)repaint(before.union(activity.getBounds()));else if(previous!=fraction)dormantDirty=true;
        }
    }
    private void releaseOutgoing(){if(outgoing!=null)outgoing.flush();outgoing=null;}
    private static void paintChild(Graphics2D graphics,Component child,float alpha) {
        if(!child.isVisible() || alpha<=0)return;
        Graphics2D g=(Graphics2D)graphics.create(child.getX(),child.getY(),child.getWidth(),child.getHeight());
        try{g.setComposite(AlphaComposite.SrcOver.derive(alpha));child.printAll(g);}finally{g.dispose();}
    }
    @Override protected void paintChildren(Graphics graphics) {
        // Swing must own child traversal. Calling paint() on a transparent,
        // double-buffered descendant here can repaint its opaque ancestor into
        // the child's coordinates (duplicating and clipping the entire summary).
        if(!completed || completionFraction>=1){super.paintChildren(graphics);return;}
        Graphics2D g=(Graphics2D)graphics.create();
        try {
            float alpha=(float)(1-Math.pow(1-completionFraction,3));
            if(outgoing!=null){g.setComposite(AlphaComposite.SrcOver.derive(1-alpha));g.drawImage(outgoing,0,0,null);}
            g.setComposite(AlphaComposite.SrcOver.derive(alpha));
            super.paintChildren(g);
        }finally{g.dispose();}
    }
    @Override public void removeNotify(){motion.stop();super.removeNotify();syncTimer();}
    @Override public void addNotify(){super.addNotify();syncTimer();}
    @Override protected void paintComponent(Graphics graphics) {
        super.paintComponent(graphics);Graphics2D g=(Graphics2D)graphics.create();
        try {
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            Shape card=new RoundRectangle2D.Float(24,8,Math.max(0,getWidth()-48),Math.max(0,getHeight()-16),14,14);
            g.setColor(MistWorkspaceTheme.SOFT);g.fill(card);g.setColor(new Color(0xd8e5f5));g.draw(card);
        }finally{g.dispose();}
    }
    @Override public void close(){if(closed)return;closed=true;releaseOutgoing();motion.stop();dormantCleanup=dormantDirty=false;stopObserving.run();}
}
