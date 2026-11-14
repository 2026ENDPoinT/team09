package dev.synesis.poc.pdf;

import dev.synesis.poc.ui.LibraryDesign;
import javax.swing.*;
import javax.imageio.ImageIO;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import org.apache.pdfbox.pdmodel.*;
import org.apache.pdfbox.pdmodel.font.*;

/** Actual shelf wiring, exported object geometry, custom appearance and responsive grid. */
public final class PdfLibraryShelfRedesignTest {
    static int checks;
    static final Path OUT=Path.of("tmp/library-redesign-20261022");
    static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    static Object get(Object o,String name)throws Exception{Field f=o.getClass().getDeclaredField(name);f.setAccessible(true);return f.get(o);}
    static void layout(Container c){c.doLayout();for(Component x:c.getComponents())if(x.isVisible()&&x instanceof Container n)layout(n);}
    static BufferedImage paint(JComponent c){BufferedImage image=new BufferedImage(c.getWidth(),c.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,c.getWidth(),c.getHeight());c.printAll(g);g.dispose();return image;}
    static List<JButton> buttons(Container c){List<JButton> result=new ArrayList<>();for(Component x:c.getComponents()){if(x instanceof JButton b)result.add(b);if(x instanceof Container n)result.addAll(buttons(n));}return result;}
    public static void main(String[] args)throws Exception{
        Files.createDirectories(OUT);Path base=Files.createTempDirectory("library-shelf-redesign-"),root=base.resolve("library");System.setProperty("synesis.dataRoot",base.resolve("user-data").toString());
        PdfLibraryOrganization org=PdfLibraryOrganization.load(root);
        String[] names={"금융강의","훈민이가 준 거","의미없는것들","현예이","수업 자료"},colors={"#246e50","#87416f","#405575","#285fa7","#9d661e"};
        List<PdfLibraryOrganization.Folder> folders=new ArrayList<>();
        for(int i=0;i<5;i++){var folder=org.createFolder("",names[i]);org.setColor(folder.id(),colors[i]);folders.add(org.folder(folder.id()));}
        for(int i=0;i<3;i++){
            Path file=base.resolve(new String[]{"선물옵션과 금융.pdf","한국사의 이해.pdf","불평등 한국 (1).pdf"}[i]);
            try(PDDocument pdf=new PDDocument()){
                PDPage page=new PDPage();pdf.addPage(page);try(var stream=new PDPageContentStream(pdf,page)){stream.beginText();stream.setFont(new PDType1Font(Standard14Fonts.FontName.HELVETICA_BOLD),28);stream.newLineAtOffset(60,700);stream.showText("Lecture "+(i+1));stream.endText();}
                for(int j=0;j<i+1;j++)pdf.addPage(new PDPage());pdf.save(file.toFile());
            }
            try(PdfSource source=PdfSource.open(file,root)){}
        }
        PdfLibraryPanel[] holder={null};SwingUtilities.invokeAndWait(()->holder[0]=new PdfLibraryPanel(root,p->{},id->CompletableFuture.completedFuture(null),route->{}));PdfLibraryPanel panel=holder[0];
        try{
            long deadline=System.nanoTime()+10_000_000_000L;
            while(System.nanoTime()<deadline){boolean[] ready={false};SwingUtilities.invokeAndWait(()->{try{ready[0]=((List<?>)get(panel,"items")).size()==3&&((Map<?,?>)get(panel,"pageCounts")).size()==3;}catch(Exception e){throw new RuntimeException(e);}});if(ready[0])break;Thread.sleep(25);}
            SwingUtilities.invokeAndWait(()->{try{
                panel.setSize(1600,900);layout(panel);layout(panel);layout(panel);JPanel grid=(JPanel)get(panel,"grid");GridLayout gridLayout=(GridLayout)grid.getLayout();
                check(gridLayout.getColumns()==5&&gridLayout.getHgap()==24&&gridLayout.getVgap()==28,"Figma five-column spacing at 1600px");
                check(grid.getComponentCount()==8,"five folders and three live files");
                for(Component tile:grid.getComponents()){
                    check(tile.getHeight()==260,"260px object tiles");check(((JComponent)tile).getTransferHandler()!=null,"object tile keeps drag handler");
                    List<JButton> menus=buttons((Container)tile);check(menus.size()>=1&&menus.get(0).getWidth()==28&&menus.get(0).getHeight()==28,"28px outlined menu target");
                    check(menus.get(0).getActionListeners().length>0,"menu is connected");
                }
                ImageIO.write(paint(panel),"png",OUT.resolve("screen-1600.png").toFile());
                ImageIO.write(paint(grid),"png",OUT.resolve("shelf-1600.png").toFile());
                Map<?,?> icons=(Map<?,?>)get(panel,"folderIcons");for(Object value:icons.values()){Icon icon=((JLabel)value).getIcon();check(icon.getIconWidth()==198&&icon.getIconHeight()==158,"exported folder geometry retained");}
                Icon green=LibraryShelfDesign.folder(Color.decode("#20965e"),null),red=LibraryShelfDesign.folder(Color.decode("#d9374b"),null);
                BufferedImage a=icon(green),b=icon(red);check(!Arrays.equals(a.getRGB(0,0,198,158,null,0,198),b.getRGB(0,0,198,158,null,0,198)),"saved color changes folder artwork");
                Icon marked=LibraryShelfDesign.folder(Color.decode("#20965e"),LibraryDesign.coloredIcon("chart",14,14,new Color(0x176b40)));
                check(!Arrays.equals(icon(marked).getRGB(0,0,198,158,null,0,198),a.getRGB(0,0,198,158,null,0,198)),"custom icon remains visible on folder artwork");
                Method actions=PdfLibraryPanel.class.getDeclaredMethod("folderActions",PdfLibraryOrganization.Folder.class,JPanel.class,JButton.class);actions.setAccessible(true);
                JPanel card=(JPanel)((Map<?,?>)get(panel,"folderCards")).get(folders.get(0).id());
                JPopupMenu popup=(JPopupMenu)actions.invoke(panel,folders.get(0),card,new JButton());
                List<String> menuNames=Arrays.stream(popup.getComponents()).filter(x->x instanceof JMenuItem).map(x->((JMenuItem)x).getText()).toList();
                check(menuNames.containsAll(List.of("아이콘 변경","색상 변경","이름 변경","폴더 열기","폴더 삭제")),"all existing folder actions retained");
                popup.setSize(popup.getPreferredSize());layout(popup);ImageIO.write(paint(popup),"png",OUT.resolve("folder-menu.png").toFile());
                for(int width:new int[]{1200,900,650}){panel.setSize(width,900);layout(panel);layout(panel);layout(panel);check(grid.getWidth()<=((JScrollPane)get(panel,"scroll")).getViewport().getWidth(),"no horizontal overflow at "+width);for(Component tile:grid.getComponents())check(tile.getHeight()>=260,"tiles never collapse at "+width+" actual="+tile.getHeight()+" grid="+grid.getSize()+" preferred="+grid.getPreferredSize()+" minimum="+grid.getMinimumSize());ImageIO.write(paint(panel),"png",OUT.resolve("screen-"+width+".png").toFile());}
            }catch(Exception e){throw new RuntimeException(e);}});
            org.setIcon(folders.get(0).id(),"chart");org.setColor(folders.get(0).id(),"#326fca");var restored=PdfLibraryOrganization.load(root).folder(folders.get(0).id());
            check(restored.icon().equals("chart")&&restored.color().equals("#326fca"),"existing icon/color persistence remains intact");
        }finally{SwingUtilities.invokeAndWait(panel::close);}
        System.out.println("PASS: "+checks+" shelf redesign checks");System.exit(0);
    }
    static BufferedImage icon(Icon icon){BufferedImage image=new BufferedImage(198,158,BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();icon.paintIcon(null,g,0,0);g.dispose();return image;}
}
