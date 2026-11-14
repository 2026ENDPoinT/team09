package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;

/** Stable login layers, pointer damage, device-scale reuse and hidden-screen buffer release. */
public final class AnimationPerformanceTest {
    private static int checks;
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{try{run();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: "+checks+" animation cache, motion, hover damage, DPI and hidden-memory checks");
    }
    private static void run()throws Exception {
        LoginPanel panel=new LoginPanel(()->{});panel.setSize(1000,700);layout(panel);
        Object paper=get(panel,"paper");
        BufferedImage first=paint(panel,1.5);
        Object surface=get(paper,"cachedSurface");
        BufferedImage second=paint(panel,1.5);
        check(surface==get(paper,"cachedSurface"),"steady frames reuse the static login surface");
        check(java.util.Arrays.equals(first.getRGB(0,0,first.getWidth(),first.getHeight(),null,0,first.getWidth()),
            second.getRGB(0,0,second.getWidth(),second.getHeight(),null,0,second.getWidth())),"cached frames preserve stable pixels");
        call(paper,"followPointer",new Class<?>[]{Point.class},new Point(160,350));
        Rectangle dirty=(Rectangle)call(paper,"updateDots",new Class<?>[]{double.class},.016);
        JComponent paperComponent=(JComponent)paper;
        check(dirty!=null&&dirty.width*dirty.height<paperComponent.getWidth()*paperComponent.getHeight(),"hover repaints only nearby dots");
        double[] offsetsX=(double[])get(paper,"dotOffsetX"),offsetsY=(double[])get(paper,"dotOffsetY");
        int nearest=14*(int)get(paper,"dotColumns")+6;
        check(offsetsX[nearest]<0&&offsetsY[nearest]<0,"nearby dots move away from the pointer in both axes");
        boolean bounded=true;for(int i=0;i<offsetsX.length;i++)bounded&=Math.hypot(offsetsX[i],offsetsY[i])<=11.001;
        check(bounded,"repulsion stays subtle and bounded");
        BufferedImage moving=paint(panel,1.5);
        BufferedImage clipped=new BufferedImage(first.getWidth(),first.getHeight(),BufferedImage.TYPE_INT_RGB);
        Graphics2D patch=clipped.createGraphics();
        try {patch.drawImage(first,0,0,null);patch.scale(1.5,1.5);patch.clip(dirty);panel.printAll(patch);}
        finally {patch.dispose();}
        check(java.util.Arrays.equals(clipped.getRGB(0,0,clipped.getWidth(),clipped.getHeight(),null,0,clipped.getWidth()),
            moving.getRGB(0,0,moving.getWidth(),moving.getHeight(),null,0,moving.getWidth())),"partial repaint covers displaced dots without trails");
        check(surface==get(paper,"cachedSurface"),"pointer motion retains the static surface");
        check(!java.util.Arrays.equals(first.getRGB(0,0,first.getWidth(),first.getHeight(),null,0,first.getWidth()),
            moving.getRGB(0,0,moving.getWidth(),moving.getHeight(),null,0,moving.getWidth())),"existing dots respond to the pointer");
        call(paper,"releaseSurface",new Class<?>[0]);
        check(get(paper,"cachedSurface")==null,"hidden-screen render buffer is released");
        paint(panel,1.5);check(get(paper,"cachedSurface")!=surface,"returning to login reconstructs its surface");
        BufferedImage scaled=(BufferedImage)get(paper,"cachedSurface");
        check(scaled.getWidth()==1500&&scaled.getHeight()==1050,"login surface preserves device resolution");
        Rectangle button=panel.loginButton().getBounds();
        check(button.width==344&&button.height==54&&button.getCenterX()==500,"Google button stays centered in the reference card");
        call(paper,"followPointer",new Class<?>[]{Point.class},new Point((int)button.getCenterX(),(int)button.getCenterY()));
        check(call(paper,"updateDots",new Class<?>[]{double.class},.016)!=null,"hover routing also works over the login control");
        panel.loginButton().setText("로그인 중…");panel.loginButton().setEnabled(false);panel.reset();
        check(panel.loginButton().isEnabled()&&panel.loginButton().getText().equals("Google로 계속하기"),"logout restores the login control");
        Rectangle restingButton=panel.loginButton().getBounds();
        BufferedImage resting=paint(panel.loginButton(),1);
        panel.loginButton().getModel().setRollover(true);
        BufferedImage hovering=paint(panel.loginButton(),1);
        check(!panel.loginButton().isRolloverEnabled(),"button hover animation is disabled");
        check(java.util.Arrays.equals(resting.getRGB(0,0,resting.getWidth(),resting.getHeight(),null,0,resting.getWidth()),
            hovering.getRGB(0,0,hovering.getWidth(),hovering.getHeight(),null,0,hovering.getWidth())),"hover leaves button pixels unchanged");
        check(panel.loginButton().getBounds().equals(restingButton),"hover does not move or enlarge the button");
        panel.loginButton().getModel().setRollover(false);
        call(paper,"followPointer",new Class<?>[]{Point.class},new Point(-1000,-1000));
        for(int i=0;i<150;i++)call(paper,"updateDots",new Class<?>[]{double.class},.016);
        check(call(paper,"updateDots",new Class<?>[]{double.class},.016)!=null,"outside-window wave keeps requesting frames");
        boolean fixed=true;for(double offset:(double[])get(paper,"dotOffsetX"))fixed&=offset==0;
        for(double offset:(double[])get(paper,"dotOffsetY"))fixed&=offset==0;
        check(fixed,"outside-window wave keeps dots at their original positions");
        call(paper,"followPointer",new Class<?>[]{Point.class},new Point(160,350));
        for(int i=0;i<150;i++)call(paper,"updateDots",new Class<?>[]{double.class},.016);
        Timer animation=(Timer)get(panel,"animation");animation.start();
        call(panel,"tick",new Class<?>[0]);
        check(!animation.isRunning(),"idle login stops its animation timer");
        Icon icon=BrandLogo.wordmark(110);check(icon==BrandLogo.wordmark(110),"wordmark icons are shared");
        BufferedImage canvas=new BufferedImage(400,150,BufferedImage.TYPE_INT_RGB);Graphics2D g=canvas.createGraphics();
        try {
            g.scale(1.25,1.25);icon.paintIcon(panel,g,0,0);Object raster=get(icon,"raster");
            icon.paintIcon(panel,g,0,0);check(raster==get(icon,"raster"),"normal icon painting does not resample artwork");
            g.scale(1.6,1.6);icon.paintIcon(panel,g,0,0);
            check(get(icon,"raster")!=raster&&((BufferedImage)get(icon,"raster")).getWidth()==220,"moving to a different DPI rebuilds exactly one raster");
        } finally {g.dispose();}
        check(StudyTheme.font(Font.PLAIN,14)==StudyTheme.font(Font.PLAIN,14),"shared fonts avoid frame allocations");
    }
    private static void check(boolean value,String reason){checks++;if(!value)throw new AssertionError(reason);}
    private static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    private static Object call(Object o,String name,Class<?>[] types,Object... args)throws Exception{Method m=o.getClass().getDeclaredMethod(name,types);m.setAccessible(true);return m.invoke(o,args);}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    private static BufferedImage paint(JComponent c,double scale){BufferedImage image=new BufferedImage((int)Math.ceil(c.getWidth()*scale),(int)Math.ceil(c.getHeight()*scale),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();try{g.scale(scale,scale);c.printAll(g);}finally{g.dispose();}return image;}
}
