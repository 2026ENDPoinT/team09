package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.MistWorkspaceTheme;
import dev.synesis.poc.ui.PanelCloseButtons;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicInteger;

/** Exercises the native header's responsive controls offscreen. */
public final class SummaryHeaderTest {
    public static void main(String[] args)throws Exception {
        SwingUtilities.invokeAndWait(()->{
            try{
                AtomicInteger fontClicks=new AtomicInteger(),closeClicks=new AtomicInteger();
                JButton font=new JButton("Aa · 글자 크기 조절");MistWorkspaceTheme.button(font,false);font.addActionListener(e->fontClicks.incrementAndGet());
                JButton close=PanelCloseButtons.close("강의 해설 창 닫기",closeClicks::incrementAndGet);
                JLabel title=MistWorkspaceTheme.label("강의 해설",18,MistWorkspaceTheme.INK,Font.BOLD);
                SummaryHeader header=new SummaryHeader(font,close,title);
                check(header.getComponentCount()==3,"Header contains only the title, font size and close controls");
                header.setSize(768,42);header.doLayout();
                check(font.getText().contains("글자 크기"),"Wide header uses the full font label");
                int switches=0;boolean previous=false;
                for(int width=768;width>=120;width--){
                    header.setSize(width,42);header.doLayout();
                    boolean compact=font.getText().equals("Aa");if(compact!=previous){switches++;previous=compact;}
                    for(Component a:header.getComponents())if(a.isVisible()){
                        check(a.getX()>=0&&a.getX()+a.getWidth()<=width,"Visible header control remains within the row");
                        for(Component b:header.getComponents())if(b!=a&&b.isVisible())check(!a.getBounds().intersects(b.getBounds()),"Header controls must never overlap");
                    }
                }
                check(switches==1,"Width threshold must not flicker between modes");
                check(font.getToolTipText().contains("글자 크기")&&close.getToolTipText().contains("창 닫기"),"Compact buttons explain their actions on hover");
                check(font.getWidth()-font.getInsets().left-font.getInsets().right>=font.getFontMetrics(font.getFont()).stringWidth("Aa"),"Aa must fit without ellipsis");
                font.doClick();check(fontClicks.get()==1,"Compact font button preserves the existing action");
                close.doClick();check(closeClicks.get()==1,"Close button preserves the existing action");
                for(int width:new int[]{340,768}){
                    header.setSize(width,42);header.doLayout();
                    BufferedImage image=new BufferedImage(width,42,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();header.printAll(g);g.dispose();
                    Files.createDirectories(Path.of("build/summary-header-20261017"));
                    javax.imageio.ImageIO.write(image,"png",Path.of("build/summary-header-20261017/"+width+".png").toFile());
                }
                check(font.getText().equals("Aa · 글자 크기 조절"),"Widening restores the full font label");
                check(fontClicks.get()==1&&closeClicks.get()==1,"Resizing never invokes actions");
            }catch(Exception error){throw new RuntimeException(error);}
        });
        System.out.println("PASS: responsive summary header, no overlaps, hover descriptions, Aa fit and action preservation");System.exit(0);
    }
    private static void check(boolean condition,String message){if(!condition)throw new AssertionError(message);}
}
