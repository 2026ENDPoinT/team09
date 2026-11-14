package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.Field;
import java.nio.file.*;
import java.util.List;
import java.util.ArrayList;
import javax.imageio.ImageIO;
import javax.swing.*;

/** Real local overlays for short/long summary and concept outlines, without app data. */
public final class OutlinePopupSizingTest {
    private static final Path OUT=Path.of("build/outline-popup-sizing");
    public static void main(String[] args)throws Exception {
        Files.createDirectories(OUT);
        SwingUtilities.invokeAndWait(()->{try {summary();concept();}catch(Exception e){throw new RuntimeException(e);}});
        System.out.println("PASS: short and long summary/concept overlays fit content, scroll and preserve navigation");System.exit(0);
    }
    private static JRootPane root(){JRootPane root=new JRootPane();root.setSize(648,900);root.getContentPane().setLayout(null);root.doLayout();return root;}
    private static JScrollPane host(JPanel list){return new JScrollPane(list){@Override public boolean isShowing(){return true;}};}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container box)layout(box);}
    private static void summary()throws Exception {
        JRootPane root=root();JPanel list=new JPanel();JScrollPane host=host(list);host.setBounds(0,50,648,850);root.getContentPane().add(host);
        JButton button=new JButton("목차");button.setBounds(550,5,76,35);root.getContentPane().add(button);
        SummaryOutlinePopup popup=new SummaryOutlinePopup();SummaryOutlineTree tree=new SummaryOutlineTree();JScrollPane contents=new JScrollPane(tree);contents.setBorder(null);contents.setPreferredSize(new Dimension(300,360));popup.add(contents);
        int[] rows={9};SummaryOutlineHover control=new SummaryOutlineHover(host,button,popup,()->true,()->{
            var model=new javax.swing.tree.DefaultMutableTreeNode("목차");for(int i=0;i<rows[0];i++)model.add(new javax.swing.tree.DefaultMutableTreeNode("목차 제목 "+i));tree.setModel(new javax.swing.tree.DefaultTreeModel(model));
        },()->{});
        try {
            layout(root);control.explicitOpen();settle(popup);check(popup.getHeight()<350,"Short summary has excess blank height");check(!contents.getVerticalScrollBar().isVisible(),"Short summary unnecessarily scrolls");snapshot(root,"summary-short");
            popup.close();rows[0]=80;control.explicitOpen();settle(popup);check(popup.getHeight()==540,"Long summary exceeds height cap");check(contents.getVerticalScrollBar().isVisible(),"Long summary cannot scroll");snapshot(root,"summary-long");
        }finally{control.close();}
    }
    private static void concept()throws Exception {
        JRootPane root=root();JPanel list=new JPanel();list.setLayout(new BoxLayout(list,BoxLayout.Y_AXIS));JScrollPane scroll=host(list);
        ConceptOverview overview=new ConceptOverview(list,scroll,new JSlider(6,64,16),new JComboBox<>(new String[]{"전체 자료"}),new JButton());overview.setBounds(0,0,648,900);root.getContentPane().add(overview);
        Field field=ConceptOverview.class.getDeclaredField("outline");field.setAccessible(true);ConceptOutlineNavigation nav=(ConceptOutlineNavigation)field.get(overview);
        Field menuField=ConceptOutlineNavigation.class.getDeclaredField("popup");menuField.setAccessible(true);SummaryOutlinePopup popup=(SummaryOutlinePopup)menuField.get(nav);
        try {
            for(int count:new int[]{4,40}){
                List<ConceptOverview.Card> cards=new ArrayList<>();List<ConceptOutline.Group> groups=new ArrayList<>();
                for(int i=0;i<count;i++){ConceptOverview.Card card=new ConceptOverview.Card("card"+i,overview,false,open->{},page->{});card.update("개념 "+i,List.of(1),"",JPanel::new);cards.add(card);groups.add(new ConceptOutline.Group("group"+i,"단원 "+i,List.of(i)));}
                overview.showCards("fixture",cards,"안내",groups);layout(root);list.setSize(scroll.getViewport().getWidth(),list.getPreferredSize().height);layout(list);
                nav.button.doClick();settle(popup);JScrollPane contents=(JScrollPane)popup.getComponent(0);
                JTree tree=(JTree)contents.getViewport().getView();
                check(tree.getRowCount()==count*2,"Concept headings or individual concepts missing");
                for(int i=0;i<count;i++){
                    var heading=tree.getPathForRow(i*2);var leaf=tree.getPathForRow(i*2+1);
                    var entry=(SummaryOutline.Entry)((javax.swing.tree.DefaultMutableTreeNode)leaf.getLastPathComponent()).getUserObject();
                    check(leaf.getParentPath().equals(heading)&&entry.title().equals("개념 "+i),"Concept leaf has wrong parent or order");
                }
                check(count==4?popup.getHeight()<350:popup.getHeight()==540,"Concept TOC does not fit content");
                check(contents.getVerticalScrollBar().isVisible()==(count==40),"Concept scroll threshold incorrect");snapshot(root,count==4?"concept-short":"concept-long");
                int selected=count/2;
                tree.setSelectionPath(tree.getPathForRow(selected*2+1));
                tree.getActionMap().get("concept-outline-jump").actionPerformed(new java.awt.event.ActionEvent(tree,0,"jump"));
                int expected=Math.min(cards.get(selected).getY(),Math.max(0,list.getHeight()-scroll.getViewport().getHeight()));
                check(scroll.getViewport().getViewPosition().y==expected,"Concept leaf did not navigate to its card");
                popup.close();
                overview.search.setText("개념 "+(count-1));
                var filter=ConceptOverview.class.getDeclaredMethod("filter");filter.setAccessible(true);filter.invoke(overview);layout(root);
                nav.button.doClick();settle(popup);
                check(tree.getRowCount()==2,"Filtered TOC kept hidden concepts or lost the matching leaf");
                popup.close();overview.search.setText("");filter.invoke(overview);
            }
        }finally{overview.dispose();}
    }
    private static void settle(SummaryOutlinePopup popup)throws Exception {Field started=SummaryOutlinePopup.class.getDeclaredField("started");started.setAccessible(true);started.setLong(popup,System.nanoTime()-500_000_000L);var method=SummaryOutlinePopup.class.getDeclaredMethod("advance");method.setAccessible(true);method.invoke(popup);}
    private static void snapshot(JRootPane root,String name)throws Exception {BufferedImage image=new BufferedImage(root.getWidth(),root.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();root.paint(g);g.dispose();ImageIO.write(image,"png",OUT.resolve(name+".png").toFile());}
    private static void check(boolean ok,String message){if(!ok)throw new AssertionError(message);}
}
