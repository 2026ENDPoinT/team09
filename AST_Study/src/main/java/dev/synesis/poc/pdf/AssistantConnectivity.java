package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.net.*;
import java.util.concurrent.*;
import java.util.function.BooleanSupplier;
import javax.swing.*;

/** Independent, bounded connectivity probe; never blocks the EDT or assistant worker. */
final class AssistantConnectivity extends JLabel implements AutoCloseable {
    private final ScheduledExecutorService checks=Executors.newSingleThreadScheduledExecutor(r->{
        Thread thread=new Thread(r,"assistant-connectivity");thread.setDaemon(true);return thread;
    });
    private final BooleanSupplier probe;
    private ScheduledFuture<?> pending;
    private int generation;
    private boolean closed;
    AssistantConnectivity(){this(AssistantConnectivity::reachable);}
    AssistantConnectivity(BooleanSupplier probe){
        this.probe=probe;setFont(dev.synesis.poc.ui.LibraryDesign.medium(11));
        setForeground(AssistantChatTheme.MUTED);setIconTextGap(6);
        setPreferredSize(new Dimension(78,30));setToolTipText("인터넷 연결 상태");showOnline(false);
    }
    void monitor(boolean enabled){
        if(closed)return;
        if(enabled&&pending==null){
            int ticket=++generation;
            pending=checks.scheduleWithFixedDelay(()->{
                boolean online;try{online=probe.getAsBoolean();}catch(RuntimeException failure){online=false;}
                boolean state=online;
                SwingUtilities.invokeLater(()->{if(!closed&&ticket==generation)showOnline(state);});
            },0,20,TimeUnit.SECONDS);
        }else if(!enabled&&pending!=null){generation++;pending.cancel(false);pending=null;}
    }
    void showOnline(boolean online){
        setText(online?"Online":"Offline");setIcon(online?ONLINE:OFFLINE);
        getAccessibleContext().setAccessibleName("인터넷 "+getText());
    }
    private static Icon dot(Color color){return new Icon(){
        public int getIconWidth(){return 8;}public int getIconHeight(){return 8;}
        public void paintIcon(Component c,Graphics graphics,int x,int y){
            Graphics2D g=(Graphics2D)graphics.create();
            try{g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);g.setColor(color);g.fillOval(x,y,8,8);}finally{g.dispose();}
        }
    };}
    /** One shared 32px raster (~4 KiB), drawn at 16px for sharp HiDPI glow.
     * No timer, blur pass, or per-paint image allocation. */
    private static Icon onlineGlow(){
        BufferedImage image=new BufferedImage(32,32,BufferedImage.TYPE_INT_ARGB);
        Graphics2D g=image.createGraphics();
        try{
            g.setRenderingHint(RenderingHints.KEY_ANTIALIASING,RenderingHints.VALUE_ANTIALIAS_ON);
            g.setPaint(new RadialGradientPaint(16,16,16,new float[]{0,.35f,.65f,1},
                new Color[]{new Color(69,218,140,130),new Color(69,218,140,90),new Color(69,218,140,30),new Color(69,218,140,0)}));
            g.fillOval(0,0,32,32);
            g.setColor(new Color(0x45DA8C));g.fillOval(8,8,16,16);
            g.setColor(new Color(225,255,238,165));g.fillOval(11,10,5,4);
        }finally{g.dispose();}
        return new Icon(){
            public int getIconWidth(){return 16;}public int getIconHeight(){return 16;}
            public void paintIcon(Component c,Graphics graphics,int x,int y){graphics.drawImage(image,x,y,16,16,null);}
        };
    }
    private static final Icon ONLINE=onlineGlow(),OFFLINE=dot(new Color(0xef6a75));
    private static boolean reachable(){
        HttpURLConnection connection=null;
        try{
            connection=(HttpURLConnection)URI.create("https://connectivitycheck.gstatic.com/generate_204").toURL().openConnection();
            connection.setConnectTimeout(2000);connection.setReadTimeout(2000);
            connection.setInstanceFollowRedirects(false);connection.setUseCaches(false);
            return connection.getResponseCode()==204;
        }catch(Exception failure){return false;}finally{if(connection!=null)connection.disconnect();}
    }
    @Override public void close(){closed=true;generation++;if(pending!=null)pending.cancel(false);pending=null;checks.shutdownNow();}
}
