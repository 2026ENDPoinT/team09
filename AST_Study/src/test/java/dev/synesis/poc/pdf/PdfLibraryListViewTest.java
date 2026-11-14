package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.CompletableFuture;
import java.util.concurrent.atomic.AtomicReference;
import java.util.function.BooleanSupplier;
import javax.imageio.ImageIO;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;

/** Real shelf toggles, metadata, folder navigation, selection and row geometry; no visible windows. */
public final class PdfLibraryListViewTest {
    public static void main(String[] args)throws Exception {
        Path base=Files.createTempDirectory("synesis-library-list-"),root=base.resolve("library");
        AtomicReference<Path> opened=new AtomicReference<>();PdfLibraryPanel[] panel={null};
        try {
            PdfLibraryOrganization folders=PdfLibraryOrganization.load(root);
            var folder=folders.createFolder("","수업 자료");folders.createFolder("","긴 폴더 이름도 목록에 보여요");
            List<String> ids=new ArrayList<>();
            for(int i=0;i<3;i++){
                Path file=base.resolve(i==0?"첫 번째 문서.pdf":i==1?"second document.pdf":"폴더 안 문서.pdf");
                try(PDDocument document=new PDDocument()){for(int p=0;p<i+2;p++)document.addPage(new PDPage());document.save(file.toFile());}
                try(PdfSource source=PdfSource.open(file,root)){ids.add(source.id);}
            }
            folders.moveDocument(ids.get(2),folder.id());
            SwingUtilities.invokeAndWait(()->panel[0]=new PdfLibraryPanel(root,opened::set,id->CompletableFuture.completedFuture(null),route->{}));
            PdfLibraryPanel library=panel[0];
            await(()->{try{return ((List<?>)get(library,"items")).size()==3&&((Map<?,?>)get(library,"pageCounts")).size()==3;}catch(Exception e){throw new RuntimeException(e);}});
            SwingUtilities.invokeAndWait(()->{try{
                JToggleButton list=toggle(library,"목록 보기"),gridToggle=toggle(library,"격자 보기");
                check(list!=null&&gridToggle!=null,"view switches are not accessible buttons");list.doClick();
                JPanel grid=(JPanel)get(library,"grid");
                check(grid.getLayout() instanceof BoxLayout&&grid.getComponentCount()==6,"expected header + 2 folders + trash + 2 files");
                check(list.isSelected()&&!gridToggle.isSelected(),"selected switch is wrong");
                grid.setSize(1100,grid.getPreferredSize().height);layout(grid);
                Component[] rows=grid.getComponents();
                check(((Container)rows[0]).getComponentCount()==7,"wrong column count");
                for(int i=1;i<rows.length;i++){
                    Container row=(Container)rows[i];check(row.getComponentCount()==7&&row.getHeight()==54,"row geometry is wrong");
                    check(row.getY()>=rows[i-1].getY()+rows[i-1].getHeight(),"rows overlap");
                    for(int col=0;col<7;col++)check(row.getComponent(col).getX()==((Container)rows[0]).getComponent(col).getX(),"column alignment differs");
                    check(row.getComponent(6) instanceof JButton,"missing row menu");
                    if(row.getName().equals("library-list-folder-"+PdfLibraryOrganization.TRASH_ID))
                        check(((JComponent)row).getTransferHandler()==null,"system trash can be dragged");
                    else check(((JComponent)row).getTransferHandler()!=null,"row drag was lost");
                }
                Map<?,?> documents=(Map<?,?>)get(library,"documentCards");Container first=(Container)documents.get(ids.get(0));
                check(((JLabel)first.getComponent(2)).getText().equals("파일"),"file kind missing");
                check(((JLabel)first.getComponent(3)).getText().matches("\\d{4}-\\d{2}-\\d{2}"),"upload date missing");
                check(((JLabel)first.getComponent(5)).getText().equals("2쪽"),"page count missing");
                Path out=Path.of("build/library-list-20261017");Files.createDirectories(out);
                BufferedImage image=new BufferedImage(1100,grid.getHeight(),BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();g.setColor(Color.WHITE);g.fillRect(0,0,image.getWidth(),image.getHeight());grid.paint(g);g.dispose();ImageIO.write(image,"png",out.resolve("list.png").toFile());
                JTextField search=(JTextField)get(library,"search");search.setText("second");check(grid.getComponentCount()==2,"search ignores list mode");search.setText("");
                gridToggle.doClick();check(grid.getLayout() instanceof GridLayout&&grid.getComponentCount()==5,"grid mode did not restore cards and trash");
                list.doClick();call(library,"enterFolder",new Class<?>[]{String.class},folder.id());
                check((boolean)get(library,"listView")&&grid.getComponentCount()==2,"folder navigation lost list mode");
                check(((Map<?,?>)get(library,"documentCards")).containsKey(ids.get(2)),"folder content is wrong");
                call(library,"enterFolder",new Class<?>[]{String.class},"");
                set(library,"selectionMode",true);call(library,"showItems",new Class<?>[]{});
                Container row=(Container)((Map<?,?>)get(library,"documentCards")).get(ids.get(0));
                JCheckBox choice=findCheckbox((Container)row.getComponent(1));check(choice!=null,"selection checkbox missing");choice.doClick();
                check(((Set<?>)get(library,"selectedIds")).contains(ids.get(0)),"selection action lost");
                set(library,"selectionMode",false);call(library,"showItems",new Class<?>[]{});
                row=(Container)((Map<?,?>)get(library,"documentCards")).get(ids.get(0));row.setSize(1100,54);layout(row);
                mouse(row,MouseEvent.MOUSE_PRESSED,InputEvent.BUTTON1_DOWN_MASK,20,20);mouse(row,MouseEvent.MOUSE_DRAGGED,InputEvent.BUTTON1_DOWN_MASK,22,21);
                mouse(row,MouseEvent.MOUSE_RELEASED,0,22,21);mouse(row,MouseEvent.MOUSE_CLICKED,0,22,21);
            }catch(Exception e){throw new RuntimeException(e);}});
            await(()->opened.get()!=null);check(opened.get().equals(root.resolve(ids.get(0)).resolve("source.pdf")),"row click opens the wrong file");
            System.out.println("PdfLibraryListViewTest passed: real view toggle; seven aligned columns; cached dates/pages; search, folder navigation, selection, row opening and drag handlers.");
        }catch(Throwable error){error.printStackTrace();System.exit(1);}
        finally{if(panel[0]!=null)SwingUtilities.invokeAndWait(panel[0]::close);}
        System.exit(0);
    }
    private static void await(BooleanSupplier condition)throws Exception{long deadline=System.nanoTime()+10_000_000_000L;while(System.nanoTime()<deadline){boolean[] ready={false};SwingUtilities.invokeAndWait(()->ready[0]=condition.getAsBoolean());if(ready[0])return;Thread.sleep(20);}throw new AssertionError("background work timed out");}
    private static void layout(Container c){c.doLayout();for(Component x:c.getComponents())if(x instanceof Container child)layout(child);}
    private static JToggleButton toggle(Container c,String label){for(Component x:c.getComponents()){if(x instanceof JToggleButton b&&label.equals(b.getAccessibleContext().getAccessibleName()))return b;if(x instanceof Container child){JToggleButton found=toggle(child,label);if(found!=null)return found;}}return null;}
    private static JCheckBox findCheckbox(Container c){for(Component x:c.getComponents()){if(x instanceof JCheckBox b)return b;if(x instanceof Container child){JCheckBox b=findCheckbox(child);if(b!=null)return b;}}return null;}
    private static Object get(Object o,String n)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String n,Object v)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);f.set(o,v);}
    private static void call(Object o,String n,Class<?>[] types,Object...args)throws Exception{Method m=o.getClass().getDeclaredMethod(n,types);m.setAccessible(true);m.invoke(o,args);}
    private static void mouse(Component c,int id,int modifiers,int x,int y){c.dispatchEvent(new MouseEvent(c,id,System.currentTimeMillis(),modifiers,x,y,0,0,1,false,id==MouseEvent.MOUSE_DRAGGED?MouseEvent.NOBUTTON:MouseEvent.BUTTON1));}
    private static void check(boolean condition,String reason){if(!condition)throw new AssertionError(reason);}
}
