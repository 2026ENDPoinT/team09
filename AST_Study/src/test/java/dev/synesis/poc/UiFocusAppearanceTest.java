package dev.synesis.poc;

import dev.synesis.poc.ui.LibraryDesign;
import dev.synesis.poc.ui.MistWorkspaceTheme;
import javax.swing.*;
import javax.swing.tree.DefaultTreeCellRenderer;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.util.Arrays;

/** Focus changes must not add click outlines, or remove keyboard actions/design borders. */
public final class UiFocusAppearanceTest {
    private static final class FocusButton extends JButton {
        boolean focused;
        FocusButton(){super("확인");}
        @Override public boolean hasFocus(){return focused;}
        @Override public boolean isFocusOwner(){return focused;}
    }
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            Insets before=UIManager.getBorder("List.focusCellHighlightBorder").getBorderInsets(new JLabel());
            UiFonts.install();UiFonts.install();
            require(UIManager.getBorder("List.focusCellHighlightBorder").getBorderInsets(new JLabel()).equals(before),"list focus changed row padding");
            for(String key:new String[]{"Focus.color","Button.focus","ToggleButton.focus","CheckBox.focus","RadioButton.focus","Slider.focus","TabbedPane.focus","Tree.selectionBorderColor"})
                require(UIManager.getColor(key).getAlpha()==0,"visible platform focus color: "+key);
            for(int style=0;style<5;style++){
                FocusButton button=new FocusButton();
                if(style==1||style==2)LibraryDesign.button(button,style==2);
                if(style==3||style==4)MistWorkspaceTheme.button(button,style==4);
                button.setSize(160,40);
                int[] normal=paint(button);button.focused=true;int[] focused=paint(button);
                require(Arrays.equals(normal,focused),"focus changed button appearance, style "+style);
                require(button.isFocusable()&&button.getInputMap(JComponent.WHEN_FOCUSED).get(KeyStroke.getKeyStroke("pressed SPACE"))!=null,"keyboard activation removed");
                final int[] clicks={0};button.addActionListener(e->clicks[0]++);button.doClick(0);require(clicks[0]==1,"click action removed");
            }
            JList<String> list=new JList<>(new String[]{"자료"});
            var renderer=list.getCellRenderer();
            JComponent plain=(JComponent)renderer.getListCellRendererComponent(list,"자료",0,false,false);plain.setSize(160,30);int[] normal=paint(plain);
            JComponent focused=(JComponent)renderer.getListCellRendererComponent(list,"자료",0,false,true);focused.setSize(160,30);
            require(Arrays.equals(normal,paint(focused)),"list focus drew a cell outline");
            DefaultTreeCellRenderer tree=new DefaultTreeCellRenderer();
            tree.getTreeCellRendererComponent(new JTree(),"자료",false,false,true,0,true);
            require(tree.getBorderSelectionColor().getAlpha()==0,"tree focus border remains");
        });
        System.out.println("UiFocusAppearanceTest passed: global focus colors/cell outlines suppressed, shared button pixels unchanged on focus, padding and keyboard/click actions preserved.");System.exit(0);
    }
    private static int[] paint(JComponent component){BufferedImage image=new BufferedImage(component.getWidth(),component.getHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();component.paint(g);g.dispose();return image.getRGB(0,0,image.getWidth(),image.getHeight(),null,0,image.getWidth());}
    private static void require(boolean value,String message){if(!value)throw new AssertionError(message);}
}
