package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import javax.swing.*;
import dev.synesis.poc.ui.FadingScrollBarUI;

/** Headless button lifecycle and cached-animation paint contract. */
public final class SummaryOutlineHoverTest {
    private static final class Popup extends JPopupMenu {
        boolean visible;int shows;
        @Override public boolean isVisible(){return visible;}
        @Override public void setVisible(boolean value){visible=value;}
        @Override public void show(Component invoker,int x,int y){visible=true;shows++;}
    }
    private static JScrollPane host;
    private static JButton button;
    private static Popup popup;
    private static SummaryOutlineHover hover;
    private static boolean available=true;
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            host=new JScrollPane(){@Override public boolean isShowing(){return true;}};
            host.setSize(360,500);host.doLayout();button=new JButton("목차");button.setSize(55,30);
            popup=new Popup();popup.add(new JScrollPane(new JTree()));
            hover=new SummaryOutlineHover(host,button,popup,()->available,()->{},()->{});hover.trackPopup(popup);
            host.dispatchEvent(mouse(host,MouseEvent.MOUSE_ENTERED));
        });
        waitFor(220);
        edt(()->{check(!popup.visible,"Scrollbar hover must not open outline");button.dispatchEvent(mouse(button,MouseEvent.MOUSE_ENTERED));});
        waitFor(220);
        edt(()->{
            check(popup.visible,"Button hover did not reveal outline");
            button.dispatchEvent(mouse(button,MouseEvent.MOUSE_EXITED));
            popup.getComponent(0).dispatchEvent(mouse(popup.getComponent(0),MouseEvent.MOUSE_ENTERED));
        });
        waitFor(320);
        edt(()->{
            check(popup.visible,"Pointer crossing into popup dismissed it");
            popup.getComponent(0).dispatchEvent(mouse(popup.getComponent(0),MouseEvent.MOUSE_EXITED));
        });
        waitFor(320);
        edt(()->{
            check(!popup.visible,"Leaving popup did not dismiss it");
            hover.explicitOpen();check(popup.visible,"Button click did not open outline");
        });
        waitFor(320);
        edt(()->{
            check(popup.visible,"Clicked menu should stay open");hover.explicitOpen();check(!popup.visible,"Second click should close menu");
            available=false;hover.explicitOpen();check(!popup.visible,"Empty outline opened");hover.close();
            try {sizingContract();animationContract();paletteContract();treeContract();outsideOverlayContract();compositingContract();}catch(Exception e){throw new RuntimeException(e);}
        });
        System.out.println("SummaryOutlineHoverTest passed: button-only hover/click, traversal, dismissal, empty state; cached unfold/fold paints, Retina shadow-image reuse, live backdrop and black scrollbar palette");System.exit(0);
    }
    private static void sizingContract() {
        JScrollPane host=new JScrollPane(){@Override public boolean isShowing(){return true;}};
        host.setSize(360,500);host.doLayout();JButton trigger=new JButton("목차");trigger.setSize(76,35);
        Popup menu=new Popup();menu.setBorder(BorderFactory.createEmptyBorder(18,18,18,18));
        SummaryOutlineTree tree=new SummaryOutlineTree();JScrollPane content=new JScrollPane(tree);content.setBorder(null);
        content.setPreferredSize(new Dimension(300,360));menu.add(content);
        int[] rows={3};
        SummaryOutlineHover control=new SummaryOutlineHover(host,trigger,menu,()->true,()->{
            var root=new javax.swing.tree.DefaultMutableTreeNode("목차");
            for(int i=0;i<rows[0];i++)root.add(new javax.swing.tree.DefaultMutableTreeNode("제목 "+i));
            tree.setModel(new javax.swing.tree.DefaultTreeModel(root));
        },()->{});
        try {
            control.explicitOpen();int shortHeight=menu.getPreferredSize().height;
            check(shortHeight<200,"Short TOC retained a tall empty panel: "+shortHeight);
            check(content.getPreferredSize().height>=tree.getPreferredSize().height,"Short TOC clips its last row");
            control.explicitOpen();rows[0]=80;control.explicitOpen();
            check(menu.getPreferredSize().height==480,"Long TOC did not respect available height");
            check(content.getPreferredSize().height<tree.getPreferredSize().height,"Long TOC lost its scrolling viewport");
            control.explicitOpen();rows[0]=1;control.explicitOpen();
            check(menu.getPreferredSize().height<shortHeight,"Reopening a shorter TOC reused the old height");
        }finally{control.close();}
    }
    private static void animationContract()throws Exception {
        SummaryOutlinePopup menu=new SummaryOutlinePopup();int[] paints={0};
        JPanel content=new JPanel(){@Override protected void paintComponent(Graphics g){paints[0]++;super.paintComponent(g);}};
        content.setBackground(Color.WHITE);menu.add(content);menu.setSize(290,400);menu.doLayout();
        Method capture=SummaryOutlinePopup.class.getDeclaredMethod("capture");capture.setAccessible(true);capture.invoke(menu);
        Field amount=SummaryOutlinePopup.class.getDeclaredField("amount");amount.setAccessible(true);
        int before=paints[0];BufferedImage image=new BufferedImage(290,400,BufferedImage.TYPE_INT_ARGB);
        amount.setFloat(menu,1);Graphics2D shadow=image.createGraphics();menu.paint(shadow);shadow.dispose();
        int shadowAlpha=image.getRGB(3,100)>>>24;
        check(shadowAlpha>0&&shadowAlpha<60,"Missing or overly dark local shadow: "+shadowAlpha);
        Graphics2D clear=image.createGraphics();clear.setComposite(AlphaComposite.Clear);clear.fillRect(0,0,290,400);clear.dispose();
        amount.setFloat(menu,.5f);shadow=image.createGraphics();menu.paint(shadow);shadow.dispose();
        check((image.getRGB(3,100)>>>24)<shadowAlpha,"Shadow did not fade with the cached surface");
        for(float step:new float[]{0,.2f,.5f,.9f,1,.7f,.3f}){
            amount.setFloat(menu,step);Graphics2D g=image.createGraphics();menu.paint(g);g.dispose();
            check(menu.getWidth()==290&&menu.getHeight()==400,"Animation changed layout dimensions");
        }
        check(before>0&&paints[0]==before,"Animation repainted live menu children each frame");
        check((image.getRGB(1,1)>>>24)<255,"Popup corners should be rounded");menu.close();image.flush();
    }
    private static void outsideOverlayContract()throws Exception {
        JRootPane root=new JRootPane();root.setSize(600,600);root.doLayout();
        root.getContentPane().setLayout(null);JButton trigger=new JButton("목차"),other=new JButton("본문");
        trigger.setBounds(500,10,70,30);other.setBounds(10,10,70,30);root.getContentPane().add(trigger);root.getContentPane().add(other);
        SummaryOutlinePopup menu=new SummaryOutlinePopup();JPanel contents=new JPanel();menu.add(contents);menu.setPopupSize(280,350);
        menu.show(trigger,-210,34);
        check(menu.isVisible()&&menu.getParent()==root.getLayeredPane(),"Menu did not use local overlay");
        Method event=SummaryOutlinePopup.class.getDeclaredMethod("outsideEvent",AWTEvent.class);event.setAccessible(true);
        Field target=SummaryOutlinePopup.class.getDeclaredField("target");target.setAccessible(true);
        event.invoke(menu,new MouseEvent(contents,MouseEvent.MOUSE_PRESSED,0,0,10,10,1,false));
        check(target.getFloat(menu)==1,"Inside click closed menu");
        event.invoke(menu,new MouseEvent(other,MouseEvent.MOUSE_PRESSED,0,0,10,10,1,false));
        check(target.getFloat(menu)==0,"Outside click did not start closing");
        Field started=SummaryOutlinePopup.class.getDeclaredField("started");started.setAccessible(true);started.setLong(menu,System.nanoTime()-500_000_000L);
        Method advance=SummaryOutlinePopup.class.getDeclaredMethod("advance");advance.setAccessible(true);advance.invoke(menu);
        check(!menu.isVisible()&&menu.getParent()==null,"Closing left popup background behind");
        Field listener=SummaryOutlinePopup.class.getDeclaredField("listening");listener.setAccessible(true);
        check(!listener.getBoolean(menu),"Outside-click listener leaked after close");menu.close();
    }
    private static void compositingContract()throws Exception {
        JRootPane root=new JRootPane();root.setSize(600,600);root.doLayout();
        Color[] color={new Color(0xf0c0c0)};int[] paints={0};
        JPanel reader=new JPanel(null){@Override protected void paintComponent(Graphics graphics){
            paints[0]++;graphics.setColor(color[0]);graphics.fillRect(0,0,getWidth(),getHeight());
            // Half-logical-pixel stripes expose background downsampling at Retina scale.
            Graphics2D g=(Graphics2D)graphics.create();g.setColor(Color.BLACK);
            for(int x=0;x<getWidth()*2;x+=2)g.fill(new java.awt.geom.Rectangle2D.Double(x*.5,0,.5,getHeight()));
            g.dispose();
        }};
        root.setContentPane(reader);root.doLayout();
        JButton trigger=new JButton("목차");trigger.setBounds(500,10,70,30);reader.add(trigger);
        SummaryOutlinePopup menu=new SummaryOutlinePopup();menu.add(new JPanel());menu.setPopupSize(280,350);
        menu.show(trigger,-210,34);
        check(!menu.isOpaque(),"Shadow overlay declares its transparent region opaque");
        check(paints[0]==0,"Opening took a stale study-background screenshot");
        Field started=SummaryOutlinePopup.class.getDeclaredField("started");started.setAccessible(true);started.setLong(menu,System.nanoTime()-500_000_000L);
        Method advance=SummaryOutlinePopup.class.getDeclaredMethod("advance");advance.setAccessible(true);advance.invoke(menu);
        BufferedImage image=new BufferedImage(1200,1200,BufferedImage.TYPE_INT_RGB);
        Graphics2D g=image.createGraphics();g.scale(2,2);root.paint(g);g.dispose();
        int x=menu.getX()*2,y=(menu.getY()+100)*2;
        Field surface=SummaryOutlinePopup.class.getDeclaredField("surface");surface.setAccessible(true);
        BufferedImage cached=(BufferedImage)surface.get(menu);
        check(cached.getWidth()==menu.getWidth()*2,"Shadow cache is not Retina resolution");
        int old=image.getRGB(x+1,y);
        check(image.getRGB(x,y)!=old,"Retina shadow edge lost half-pixel background detail");
        color[0]=new Color(0xc0f0c0);g=image.createGraphics();g.scale(2,2);root.paint(g);g.dispose();
        check(image.getRGB(x+1,y)!=old,"Open shadow replayed stale study content");
        check(surface.get(menu)==cached,"Scrolling regenerated the shadow image");
        menu.setVisible(false);Field amount=SummaryOutlinePopup.class.getDeclaredField("amount");amount.setAccessible(true);amount.setFloat(menu,.5f);
        color[0]=new Color(0xc0c0f0);g=image.createGraphics();g.scale(2,2);root.paint(g);g.dispose();
        int sample=image.getRGB(x+1,y);
        check((sample&255)>((sample>>>8)&255),"Closing animation restored an old background");
        menu.close();check(menu.getParent()==null,"Closed overlay remains attached");image.flush();
    }
    private static void treeContract()throws Exception {
        SummaryOutlineTree tree=new SummaryOutlineTree();
        var root=new javax.swing.tree.DefaultMutableTreeNode("목차");
        var first=new javax.swing.tree.DefaultMutableTreeNode(new SummaryOutline.Entry("a","","손익계산서",1,1,2,java.util.List.of()));
        var second=new javax.swing.tree.DefaultMutableTreeNode(new SummaryOutline.Entry("b","a","기업이 발생시키는 네 가지 비용",2,1,2,java.util.List.of()));
        root.add(first);first.add(second);tree.setModel(new javax.swing.tree.DefaultTreeModel(root));
        tree.expandRow(0);tree.current("b");
        Component normal=tree.getCellRenderer().getTreeCellRendererComponent(tree,first,false,true,false,0,false);
        check(normal.getForeground().equals(new Color(0x73726e)),"Non-current row is not neutral");
        Component active=tree.getCellRenderer().getTreeCellRendererComponent(tree,second,false,false,true,1,false);
        check(active.getForeground().equals(new Color(0x2383e2)),"Current row is not blue");
        tree.current("a");active=tree.getCellRenderer().getTreeCellRendererComponent(tree,first,false,true,false,0,false);
        check(active.getForeground().equals(new Color(0x2383e2)),"Reading highlight did not follow current heading");
    }
    private static void paletteContract()throws Exception {
        Field color=FadingScrollBarUI.class.getDeclaredField("thumbColor");color.setAccessible(true);
        check(Color.BLACK.equals(color.get(new FadingScrollBarUI())),"Global thumb is not black");
        Color tutor=new Color(0x71839d);check(tutor.equals(color.get(new FadingScrollBarUI(tutor,.38f))),"Explicit tutor colors changed");
        Field idle=FadingScrollBarUI.class.getDeclaredField("idleOpacity");idle.setAccessible(true);
        check(Math.abs(idle.getFloat(new FadingScrollBarUI(Color.BLACK,.2f))-.2f)<.001,"Outline idle opacity is not 20%");
    }
    private static MouseEvent mouse(Component c,int id){return new MouseEvent(c,id,0,0,10,10,0,false);}
    private static void waitFor(int ms)throws Exception{Thread.sleep(ms);edt(()->{});}
    private static void edt(Runnable task)throws Exception{SwingUtilities.invokeAndWait(task);}
    private static void check(boolean okay,String message){if(!okay)throw new AssertionError(message);}
}
