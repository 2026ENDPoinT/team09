package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.lang.reflect.Method;

/** Deterministic animation frames, including reversal and nested easy disclosure; no live API. */
public final class ConceptRevealTest {
    private static final class FixedBody extends JPanel {
        int boundsChanges;
        FixedBody(){setBackground(Color.BLUE);setPreferredSize(new Dimension(400,600));}
        @Override public void setBounds(int x,int y,int w,int h){
            if(w!=getWidth()||h!=getHeight())boundsChanges++;
            super.setBounds(x,y,w,h);
        }
    }
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            try {
                JPanel list=new JPanel();
                ConceptOverview owner=new ConceptOverview(list,new JScrollPane(list),new JSlider(),new JComboBox<>(),new JButton());
                JPanel host=new JPanel(null){@Override public boolean isShowing(){return true;}};
                FixedBody body=new FixedBody();
                ConceptOverview.Reveal reveal=new ConceptOverview.Reveal(body,false,owner);host.add(reveal);
                // First open starts with width zero (a hidden BorderLayout child has no bounds).
                reveal.setOpen(true);require(reveal.getPreferredSize().height==0,"first opening skipped animation");
                reveal.setSize(400,0);reveal.doLayout();int changes=body.boundsChanges;
                long start=started(reveal);int previous=0;
                for(int frame=1;frame<=14;frame++){
                    tick(reveal,start+frame*16_000_000L);int height=reveal.getPreferredSize().height;
                    require(height>=previous&&height<=600,"opening height is not monotonic");
                    reveal.setSize(400,height);reveal.doLayout();previous=height;
                    require(body.getHeight()==600,"animation resized/reflowed its body");
                }
                require(previous==600&&body.boundsChanges==changes,"height frames invalidated the body geometry");
                // Clipping reveals, rather than scales, the original component.
                reveal.setOpen(false);tick(reveal,started(reveal)+60_000_000L);
                int middle=reveal.getPreferredSize().height;require(middle>0&&middle<600,"closing has no intermediate frames");
                reveal.setSize(400,middle);reveal.doLayout();
                BufferedImage clipped=new BufferedImage(400,600,BufferedImage.TYPE_INT_ARGB);
                Graphics2D graphics=clipped.createGraphics();reveal.paint(graphics);graphics.dispose();
                require((clipped.getRGB(200,middle+1)>>>24)==0,"body painted beyond animated viewport");
                reveal.setOpen(true);require(reveal.getPreferredSize().height==middle,"quick reversal jumped");
                tick(reveal,started(reveal)+220_000_000L);require(reveal.getPreferredSize().height==600,"reopening did not finish");
                reveal.setSize(240,600);reveal.doLayout();require(body.getWidth()==240,"resizing did not propagate width");
                // Easy text expands inside an already-open article using the same viewport.
                JPanel stack=new JPanel(){@Override public boolean isShowing(){return true;}};stack.setLayout(new BoxLayout(stack,BoxLayout.Y_AXIS));
                FixedBody easyBody=new FixedBody();easyBody.setPreferredSize(new Dimension(240,180));
                ConceptOverview.Reveal easy=new ConceptOverview.Reveal(easyBody,false,owner);
                stack.add(new JLabel("기존 설명"));stack.add(easy);
                ConceptOverview.Reveal outer=new ConceptOverview.Reveal(stack,true,owner);host.add(outer);
                stack.setSize(240,400);outer.setSize(240,400);outer.doLayout();stack.doLayout();
                // Simulate a showing hierarchy without creating a window or side panel.
                easy.setSize(240,0);easy.doLayout();int before=easyBody.boundsChanges;
                int collapsedHeight=outer.getPreferredSize().height;
                easy.setOpen(true);long easyStart=started(easy);
                for(int i=1;i<=14;i++){tick(easy,easyStart+i*16_000_000L);easy.setSize(240,easy.getPreferredSize().height);easy.doLayout();stack.invalidate();}
                require(easyBody.boundsChanges==before&&easy.getPreferredSize().height==180,"easy disclosure reflowed cached text");
                require(outer.getPreferredSize().height==collapsedHeight+180,"nested easy height did not reach the outer article");
                easy.setOpen(false);tick(easy,started(easy)+220_000_000L);require(!easy.isVisible(),"closed easy content remains interactive");
                reveal.setOpen(false);reveal.removeNotify();require(reveal.getPreferredSize().height==0,"detached animation did not settle");
                owner.dispose();
            }catch(Exception error){throw new RuntimeException(error);}
        });
        System.out.println("ConceptRevealTest passed: first opening, monotonic frames, fixed body geometry, clipping, reversal, resize, easy disclosure and timer cleanup.");System.exit(0);
    }
    private static long started(ConceptOverview.Reveal reveal)throws Exception {Field f=ConceptOverview.Reveal.class.getDeclaredField("started");f.setAccessible(true);return f.getLong(reveal);}
    private static void tick(ConceptOverview.Reveal reveal,long now)throws Exception {Method m=ConceptOverview.Reveal.class.getDeclaredMethod("tick",long.class);m.setAccessible(true);m.invoke(reveal,now);}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
