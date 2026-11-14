package dev.synesis.poc.pdf;

import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.List;
import java.util.concurrent.atomic.AtomicInteger;

/** Expanded-article geometry, preserved palette, real title weight and cached disclosure. */
public final class ConceptExpandedCardTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            JPanel list=new JPanel();list.setLayout(new BoxLayout(list,BoxLayout.Y_AXIS));
            ConceptOverview overview=new ConceptOverview(list,new JScrollPane(list),new JSlider(6,64,16),new JComboBox<>(new String[]{"전체 자료"}),new JButton());
            AtomicInteger renders=new AtomicInteger();
            ConceptOverview.Card card=new ConceptOverview.Card("test/concept/one",overview,false,open->{},page->{});
            card.update("손익계산서",List.of(1),"saved",()->{renders.incrementAndGet();return new JLabel("실제 본문이 들어가는 영역");});
            overview.showCards("test",List.of(card),"");
            require(renders.get()==0,"closed row eagerly rendered");
            JButton toggle=(JButton)((Container)card.getComponent(0)).getComponent(0);
            require(toggle.getFont().getFontName().contains("Medium"),"title is not using the bundled Medium face");
            require(toggle.getBackground().getRGB()==new Color(0xf9fcff).getRGB(),"user-selected background changed");
            toggle.doClick();card.setSize(600,card.getPreferredSize().height);card.doLayout();
            Insets inset=card.getInsets();require(inset.top==1&&inset.left==1&&inset.right==1&&inset.bottom==13,"article outline/gap insets differ from Figma");
            JPanel body=(JPanel)((Container)card.getComponent(1)).getComponent(0);require(body.getInsets().equals(new Insets(16,20,16,20)),"article padding changed");
            BufferedImage image=new BufferedImage(card.getWidth(),card.getHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();card.paint(g);g.dispose();
            require((image.getRGB(0,0)>>>24)==0,"article corner is not clipped round");
            BufferedImage outline=new BufferedImage(card.getWidth(),card.getHeight(),BufferedImage.TYPE_INT_ARGB);
            Graphics2D edge=outline.createGraphics();card.getBorder().paintBorder(card,edge,0,0,card.getWidth(),card.getHeight());edge.dispose();
            for(int y=0;y<8;y++)for(int x=0;x<8;x++)
                require((image.getRGB(x,y)>>>24)>=(outline.getRGB(x,y)>>>24),"rounded border pixels were clipped");
            require((image.getRGB(8,card.getHeight()-1)>>>24)==0,"gap below expanded article was painted");
            require(toggle.getIcon().getIconWidth()==16&&toggle.getIcon().getIconHeight()==16,"expanded Figma icon slot changed");
            toggle.doClick();toggle.doClick();require(renders.get()==1,"collapse/reopen rerendered cached body");
            JButton source=ConceptOverview.sourceButton(List.of(1),page->{}),easy=new JButton("쉬운 설명 보기"),tutor=new JButton("AI멘토에게 질문");
            ConceptOverview.actionButton(easy,144,true);ConceptOverview.actionButton(tutor,168,true);JPanel actions=ConceptOverview.actions(source,easy,tutor);
            require(actions.getComponent(0)==easy&&actions.getComponent(1)==tutor&&actions.getComponent(2)==source,"footer order must be easy / tutor / source");
            for(int width:new int[]{560,530,300}){
                actions.setSize(width,160);actions.doLayout();
                for(Component control:actions.getComponents())require(control.getX()>=0&&control.getX()+control.getWidth()<=width&&control.getHeight()==36,"footer control overflowed");
                if(width>=530)require(source.getY()==0&&easy.getY()==0&&tutor.getY()==0,"wide action row unexpectedly wrapped");
                else require(tutor.getY()>easy.getY(),"narrow action controls overlap");
            }
            overview.dispose();
        });
        System.out.println("ConceptExpandedCardTest passed: rounded 1px article, 20×16 padding, preserved palette, Medium title, 16px asset and responsive/cached controls.");System.exit(0);
    }
    private static void require(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
