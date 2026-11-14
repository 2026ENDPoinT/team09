package dev.synesis.poc.ui;

import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.event.HierarchyEvent;
import java.awt.geom.RoundRectangle2D;
import java.awt.image.BufferedImage;
import java.util.concurrent.CompletableFuture;
import java.util.LinkedHashMap;
import java.util.Map;

/** Promotion carousel with short copy and a single subscription dismissal control. */
public final class LibraryAdBanner extends JPanel implements AutoCloseable {
    private static final String[][] COPY={
        {"STARBUCKS","오늘의 공부엔, 오늘의 커피","스타벅스 리워드 회원에게 드리는 오후 음료 별 적립 혜택"},
        {"NIKE","멈추지 않는 너를 위해","가볍고 빠른 데일리 러닝화, 새로운 컬러를 만나보세요."},
        {"APPLE EDUCATION","대학생활을 더 강력하게.","Mac과 iPad 교육 할인, 그리고 신학기 특별 혜택까지."},
        {"BOOKING.COM","다음 방학은, 바다 가까이","전 세계 인기 숙소를 회원 전용 가격으로 예약하세요."},
        {"AĒSOP","매일의 균형을 위한 스킨케어","피부에 필요한 것만 담은 데일리 루틴을 시작하세요."}};
    private static final float[] POS={.58f,.54f,.62f,.56f,.52f};
    private final BufferedImage[] images=new BufferedImage[5];
    private final Timer autoplay,motion;
    private final JButton dismiss;
    private boolean modal,disposed;
    private int active,from;
    private long began;
    private double progress=1;
    private record SlideKey(int index,int width,int height,int pixelsWide,int pixelsHigh) {}
    private final Map<SlideKey,BufferedImage> slides=new LinkedHashMap<>(4,.75f,true);
    private int slideRenders;

    public LibraryAdBanner(){
        setLayout(null);setOpaque(false);setPreferredSize(new Dimension(600,176));
        setMaximumSize(new Dimension(Integer.MAX_VALUE,176));setMinimumSize(new Dimension(0,176));
        getAccessibleContext().setAccessibleName("프로모션 광고 이미지 슬라이드");
        getAccessibleContext().setAccessibleDescription(String.join(" · ",COPY[0]));
        motion=new Timer(16,e->{
            progress=Math.min(1,(System.nanoTime()-began)/650_000_000d);repaint();
            if(progress>=1)((Timer)e.getSource()).stop();
        });
        autoplay=new Timer(4000,e->{
            if(!modal&&AnimationWindow.active(this)&&getMousePosition(true)==null&&!motion.isRunning()){
                int target=(active+1)%images.length;
                if(images[target]==null)return;
                from=active;active=target;progress=0;began=System.nanoTime();motion.start();
                getAccessibleContext().setAccessibleDescription(String.join(" · ",COPY[active]));
            }
        });
        dismiss=new JButton("×"){
            @Override protected void paintComponent(Graphics graphics){
                Graphics2D g=(Graphics2D)graphics.create();
                g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
                g.setColor(new Color(0,0,0,getModel().isRollover()?155:100));
                g.fillOval(0,0,getWidth(),getHeight());g.dispose();super.paintComponent(graphics);
            }
        };
        dismiss.setFont(LibraryDesign.font(Font.PLAIN,23));dismiss.setForeground(Color.WHITE);
        dismiss.setBorder(null);dismiss.setMargin(new Insets(0,0,2,0));dismiss.setOpaque(false);
        dismiss.setContentAreaFilled(false);dismiss.setFocusPainted(false);dismiss.setRolloverEnabled(true);
        dismiss.setCursor(Cursor.getPredefinedCursor(Cursor.HAND_CURSOR));
        dismiss.getAccessibleContext().setAccessibleName("광고 닫기");
        dismiss.addActionListener(e->{
            if(modal)return;
            modal=true;autoplay.stop();motion.stop();progress=1;repaint();
            LibraryPlanPrompt.open(this,()->{modal=false;syncAnimation();});
        });
        add(dismiss);
        AnimationWindow.observe(this,this::syncAnimation);
        CompletableFuture.runAsync(()->{
            for(int i=0;i<images.length;i++)try(var in=getClass().getResourceAsStream("/dev/synesis/poc/advertising/ad-"+i+".jpg")){
                BufferedImage image=ImageIO.read(in);final int index=i;
                SwingUtilities.invokeLater(()->{images[index]=image;repaint();});
            }catch(Exception ignored){}
        });
    }
    private void syncAnimation() {
        if(!disposed&&!modal&&AnimationWindow.active(this)) {
            if(!autoplay.isRunning())autoplay.restart();
        } else {
            autoplay.stop();motion.stop();
            if(progress<1){progress=1;repaint();}
            if(!isShowing())releaseSlides();
        }
    }
    @Override public void doLayout(){dismiss.setBounds(getWidth()-38,9,28,28);}
    @Override protected void paintComponent(Graphics graphics){
        Graphics2D g=(Graphics2D)graphics.create();
        g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
        g.clip(new RoundRectangle2D.Double(0,0,getWidth(),getHeight(),24,24));
        g.setColor(new Color(0x181818));g.fillRect(0,0,getWidth(),getHeight());
        double eased=1-Math.pow(1-progress,3);
        if(progress<1){slide(g,from,(int)(-eased*getWidth()));slide(g,active,(int)((1-eased)*getWidth()));}
        else slide(g,active,0);
        g.dispose();
    }
    private void slide(Graphics2D base,int index,int x){
        BufferedImage image=images[index];if(image==null)return;
        Graphics2D g=(Graphics2D)base.create();g.translate(x,0);g.clipRect(0,0,getWidth(),getHeight());
        try {
            double sx=Math.abs(g.getTransform().getScaleX()),sy=Math.abs(g.getTransform().getScaleY());
            int pw=Math.max(1,(int)Math.ceil(getWidth()*sx)),ph=Math.max(1,(int)Math.ceil(getHeight()*sy));
            if((long)pw*ph>1_500_000){paintSlide(g,index);return;}
            SlideKey key=new SlideKey(index,getWidth(),getHeight(),pw,ph);
            BufferedImage cached=slides.get(key);
            if(cached==null) {
                cached=new BufferedImage(pw,ph,BufferedImage.TYPE_INT_RGB);
                Graphics2D raster=cached.createGraphics();
                try {raster.setRenderingHints(g.getRenderingHints());raster.scale(sx,sy);paintSlide(raster,index);}
                finally{raster.dispose();}
                slides.put(key,cached);slideRenders++;
                while(slides.size()>2){var oldest=slides.entrySet().iterator();var entry=oldest.next();entry.getValue().flush();oldest.remove();}
            }
            g.drawImage(cached,0,0,getWidth(),getHeight(),null);
        }finally{g.dispose();}
    }
    private void paintSlide(Graphics2D g,int index) {
        BufferedImage image=images[index];
        double scale=Math.max((double)getWidth()/image.getWidth(),(double)getHeight()/image.getHeight());
        int w=(int)Math.ceil(image.getWidth()*scale),h=(int)Math.ceil(image.getHeight()*scale);
        g.setRenderingHint(RenderingHints.KEY_INTERPOLATION,RenderingHints.VALUE_INTERPOLATION_BILINEAR);
        g.drawImage(image,(getWidth()-w)/2,(int)((getHeight()-h)*POS[index]),w,h,null);
        g.setPaint(new LinearGradientPaint(0,0,Math.max(1,getWidth()),0,
            new float[]{0,.45f,1},new Color[]{new Color(0,0,0,200),new Color(0,0,0,130),new Color(0,0,0,12)}));
        g.fillRect(0,0,getWidth(),getHeight());
        g.setRenderingHint(RenderingHints.KEY_TEXT_ANTIALIASING,RenderingHints.VALUE_TEXT_ANTIALIAS_ON);
        int left=getWidth()<500?24:40,available=Math.max(0,getWidth()-left-48);
        g.setFont(LibraryDesign.font(Font.BOLD,9));g.setColor(new Color(255,255,255,190));
        g.drawString(fit(g,COPY[index][0],available),left,55);
        g.setFont(LibraryDesign.font(Font.BOLD,getWidth()<500?17:22));g.setColor(Color.WHITE);
        g.drawString(fit(g,COPY[index][1],available),left,89);
        g.setFont(LibraryDesign.font(Font.PLAIN,11));g.setColor(new Color(255,255,255,205));
        g.drawString(fit(g,COPY[index][2],available),left,114);
    }
    private static String fit(Graphics2D g,String text,int width){
        FontMetrics metrics=g.getFontMetrics();if(metrics.stringWidth(text)<=width)return text;
        if(metrics.stringWidth("…")>width)return "";
        int end=text.length();while(end>0&&metrics.stringWidth(text.substring(0,end)+"…")>width)end--;
        return text.substring(0,end)+"…";
    }
    private void releaseSlides(){slides.values().forEach(BufferedImage::flush);slides.clear();}
    @Override public void removeNotify(){autoplay.stop();motion.stop();releaseSlides();super.removeNotify();}
    @Override public void close(){disposed=true;autoplay.stop();motion.stop();releaseSlides();}
}
