package dev.synesis.poc.ui;

import javax.swing.*;
import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;

/** Offscreen drag regression: stationary workspace is cached; live chat and idle cleanup survive. */
public final class FloatingMentorDragWorkTest {
    static class Counter extends JPanel {
        int paints;
        Counter(){setBackground(Color.WHITE);}
        @Override protected void paintComponent(Graphics g){paints++;super.paintComponent(g);}
    }
    static Object field(Object owner,String name){try{Field f=owner.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(owner);}catch(Exception e){throw new RuntimeException(e);}}
    static void tick(FloatingMentor mentor){try{Method m=FloatingMentor.class.getDeclaredMethod("tick");m.setAccessible(true);m.invoke(mentor);}catch(Exception e){throw new RuntimeException(e);}}
    static void mouse(JComponent source,int id,int x,int y){source.dispatchEvent(new MouseEvent(source,id,System.currentTimeMillis(),InputEvent.BUTTON1_DOWN_MASK,x,y,x,y,1,false,MouseEvent.BUTTON1));}
    static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child.isVisible()&&child instanceof Container nested)layout(nested);}
    static void check(boolean pass,String message){if(!pass)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        boolean baseline=args.length>0;
        SwingUtilities.invokeAndWait(()->{
            JLayeredPane stage=new JLayeredPane(){@Override public boolean isShowing(){return true;}@Override public boolean isOptimizedDrawingEnabled(){return false;}};
            stage.setSize(1300,1000);stage.addNotify();
            Counter workspace=new Counter();workspace.setBounds(0,0,1300,1000);stage.add(workspace,JLayeredPane.DEFAULT_LAYER);
            FloatingMentor mentor=new FloatingMentor();mentor.setBounds(0,0,1300,1000);stage.add(mentor,JLayeredPane.MODAL_LAYER);
            Counter chat=new Counter();JLabel live=new JLabel("live animation");chat.add(live);mentor.setContent(chat);mentor.setOpen(true,false);layout(stage);
            BufferedImage image=new BufferedImage(1300,1000,BufferedImage.TYPE_INT_RGB);Graphics2D graphics=image.createGraphics();stage.paint(graphics);
            workspace.paints=0;chat.paints=0;JComponent orb=(JComponent)field(mentor,"orb");mouse(orb,MouseEvent.MOUSE_PRESSED,36,36);
            for(int i=0;i<48;i++){
                double angle=i*Math.PI/12;int x=650+(int)(230*Math.sin(angle)),y=500-(int)(230*Math.cos(angle));
                mouse(orb,MouseEvent.MOUSE_DRAGGED,x-orb.getX(),y-orb.getY());tick(mentor);
                live.setText("live animation "+i);stage.paint(graphics);
            }
            System.out.println("circleFrames=48 workspacePaints="+workspace.paints+" liveChatPaints="+chat.paints);
            if(!baseline){check(workspace.paints<=2,"drag repaints stationary workspace each frame");check(chat.paints>=48,"drag freezes live chat animations");}
            mouse(orb,MouseEvent.MOUSE_RELEASED,36,36);
            // Deactivation must cancel pending motion, release the background image and stop the timer.
            try{Method settle=FloatingMentor.class.getDeclaredMethod("settle");settle.setAccessible(true);settle.invoke(mentor);}catch(Exception e){throw new RuntimeException(e);}
            if(!baseline){check(field(mentor,"backdrop")==null&&!mentor.isOpaque(),"gesture cache survives cancellation");check(!((Timer)field(mentor,"motion")).isRunning(),"idle motion timer still runs");}
            stage.paint(graphics);check(workspace.paints>0,"workspace does not return live after drag");graphics.dispose();image.flush();mentor.close();stage.removeNotify();
        });
        System.out.println("PASS FloatingMentorDragWork");System.exit(0);
    }
}
