package dev.synesis.poc.pdf;

import java.awt.*;
import java.awt.event.*;
import java.awt.image.BufferedImage;
import java.lang.reflect.*;
import java.nio.file.*;
import java.util.concurrent.atomic.AtomicInteger;
import javax.imageio.ImageIO;
import javax.swing.*;
import org.apache.pdfbox.pdmodel.*;
import dev.synesis.poc.ui.MistWorkspaceTheme;

/** Native selection/painting checks, including custom values and independent view modes. */
public final class PdfZoomControlTest {
    public static void main(String[] args)throws Exception {
        try {SwingUtilities.invokeAndWait(()->{try {run();}catch(Exception e){throw new RuntimeException(e);}});}
        catch(Throwable e){e.printStackTrace();System.exit(1);}
        System.out.println("PdfZoomControlTest passed");System.exit(0);
    }
    private static void run()throws Exception {
        Path out=Path.of("build/pdf-zoom-20261017");Files.createDirectories(out);
        Object selectionColor=UIManager.get("ComboBox.selectionForeground");
        try {
            UIManager.put("ComboBox.selectionForeground",Color.WHITE);
            JComboBox<String> focused=new JComboBox<>(new String[]{"125%"}) {
                @Override public boolean hasFocus(){return true;}
            };
            MistWorkspaceTheme.comboBox(focused,true);
            visible(focused,"125%");
        } finally {UIManager.put("ComboBox.selectionForeground",selectionColor);}
        Path file=Files.createTempFile("synesis-zoom-", ".pdf");
        try(PDDocument doc=new PDDocument()){doc.addPage(new PDPage());doc.save(file.toFile());}
        PdfWorkspace workspace=new PdfWorkspace(false,out.resolve("unused-library"));
        try {
            set(workspace,"source",PdfSource.open(file,out.resolve("unused-library")));
            call(workspace,"setControls");
            JComboBox<?> study=(JComboBox<?>)get(workspace,"zoom"),full=(JComboBox<?>)get(workspace,"fullZoom");
            JScrollPane scroll=(JScrollPane)get(workspace,"imageScroll");scroll.getViewport().setExtentSize(new Dimension(600,700));
            workspace.setPdfOnlyScreenHandler(screen->{},()->{});
            Method select=PdfWorkspace.class.getDeclaredMethod("selectPdfZoom",int.class,Point.class,Point.class);select.setAccessible(true);
            AtomicInteger generation=(AtomicInteger)get(workspace,"renderGeneration");
            BufferedImage strip=new BufferedImage(240,34*6,BufferedImage.TYPE_INT_RGB);Graphics2D g=strip.createGraphics();
            g.setColor(Color.WHITE);g.fillRect(0,0,strip.getWidth(),strip.getHeight());
            int[] values={100,105,106,125,124,200,201,90,91,500,499,25,26,33};
            for(int round=0;round<4;round++)for(int value:values) {
                int before=generation.get();select.invoke(workspace,value,null,null);
                check(generation.get()==before+1,"custom selection caused multiple PDF renders");
                visible(study,value+"%");
                check(study.getItemCount()<=16,"custom choices accumulated");
                if(round==0 && value==100)paint(study,g,0,0);
            }
            study.setSelectedItem("150%");visible(study,"150%");paint(study,g,0,34);
            call(workspace,"showPdfOnly");visible(full,"100%");visible(study,"150%");paint(full,g,120,0);
            check(percent(workspace)==100,"renderer ignored fullscreen zoom");
            select.invoke(workspace,105,null,null);visible(full,"105%");visible(study,"150%");paint(full,g,120,34);
            scroll.dispatchEvent(new MouseWheelEvent(scroll,MouseEvent.MOUSE_WHEEL,System.currentTimeMillis(),
                InputEvent.CTRL_DOWN_MASK,40,40,0,false,MouseWheelEvent.WHEEL_UNIT_SCROLL,1,-1));
            visible(full,"106%");visible(study,"150%");check(percent(workspace)==106,"fullscreen wheel used study zoom");paint(full,g,120,68);
            full.setSelectedItem("200%");visible(full,"200%");check(percent(workspace)==200,"fullscreen dropdown ignored");paint(full,g,120,102);
            call(workspace,"leavePdfOnly");visible(study,"150%");check(percent(workspace)==150,"study zoom not restored");paint(study,g,0,68);
            ((JButton)get(workspace,"zoomOut")).doClick();visible(study,"145%");visible(full,"200%");paint(study,g,0,102);
            call(workspace,"showPdfOnly");visible(full,"200%");check(percent(workspace)==200,"fullscreen choice not retained");
            ((JButton)get(workspace,"zoomIn")).doClick();visible(full,"205%");visible(study,"145%");paint(full,g,120,136);
            call(workspace,"leavePdfOnly");visible(study,"145%");paint(study,g,0,136);
            study.setSelectedItem("너비 맞춤");visible(study,"너비 맞춤");paint(study,g,0,170);
            call(workspace,"showPdfOnly");visible(full,"205%");paint(full,g,120,170);call(workspace,"leavePdfOnly");visible(study,"너비 맞춤");
            g.dispose();ImageIO.write(strip,"png",out.resolve("zoom-values.png").toFile());
        } finally {workspace.close();Files.deleteIfExists(file);}
    }
    private static double percent(PdfWorkspace w)throws Exception {
        Method m=PdfWorkspace.class.getDeclaredMethod("currentPdfZoomPercent");m.setAccessible(true);return (double)m.invoke(w);
    }
    private static void visible(JComboBox<?> box,String expected)throws Exception {
        check(expected.equals(box.getSelectedItem()),"wrong selected value: "+box.getSelectedItem()+" / "+expected);
        check(box.getSelectedIndex()>=0,"selection is missing from displayed model");
        BufferedImage image=new BufferedImage(112,34,BufferedImage.TYPE_INT_RGB);Graphics2D g=image.createGraphics();
        g.setColor(Color.WHITE);g.fillRect(0,0,112,34);box.setSize(112,34);box.doLayout();box.paint(g);g.dispose();
        int ink=0;
        for(int y=7;y<27;y++)for(int x=10;x<76;x++) {Color c=new Color(image.getRGB(x,y));if(c.getRed()<150&&c.getGreen()<170&&c.getBlue()<190)ink++;}
        if(ink<=5)ImageIO.write(image,"png",Path.of("build/pdf-zoom-20261017/blank-zoom.png").toFile());
        check(ink>5,"selected zoom text was not painted: "+expected+", pixels="+ink);
    }
    private static void paint(JComboBox<?> box,Graphics2D g,int x,int y){Graphics2D c=(Graphics2D)g.create(x,y,120,34);box.setSize(112,34);box.doLayout();box.paint(c);c.dispose();}
    private static Object get(Object o,String n)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);return f.get(o);}
    private static void set(Object o,String n,Object v)throws Exception{Field f=o.getClass().getDeclaredField(n);f.setAccessible(true);f.set(o,v);}
    private static void call(Object o,String n)throws Exception{Method m=o.getClass().getDeclaredMethod(n);m.setAccessible(true);m.invoke(o);}
    private static void check(boolean v,String why){if(!v)throw new AssertionError(why);}
}
