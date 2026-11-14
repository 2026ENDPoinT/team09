package dev.synesis.poc.ui;

import dev.synesis.poc.planner.*;
import dev.synesis.poc.planner.PlannerModel.Event;
import javax.imageio.ImageIO;
import javax.swing.*;
import java.awt.*;
import java.awt.image.BufferedImage;
import java.nio.file.*;
import java.time.*;
import java.util.*;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import static dev.synesis.poc.planner.PlannerModel.*;

/** Tag selection stays in the event draft; failed modal setup cannot leave a blocking glass pane. */
public final class PlannerTagPickerTest {
    private static int checks;
    private static final Path OUTPUT=Path.of("build/planner-tag-picker-20261018");
    private static void check(boolean value,String message){checks++;if(!value)throw new AssertionError(message);}
    public static void main(String[] args)throws Exception {
        Path root=Files.createTempDirectory("synesis-planner-tag-picker-");Files.createDirectories(OUTPUT);
        PlannerStore store=new PlannerStore(root.resolve("planner.json"));Clock clock=Clock.fixed(Instant.parse("2026-10-18T03:00:00Z"),ZoneId.of("Asia/Seoul"));
        SwingUtilities.invokeAndWait(()->{try{
            PlannerDialogs.EventEditor empty=new PlannerDialogs.EventEditor(store,State.empty(),null,LocalDateTime.of(2026,10,18,10,0),s->{},clock);
            JPanel popup=empty.tagPicker();List<JLabel> labels=find(popup,JLabel.class);
            check(labels.stream().anyMatch(l->"태그가 없어요. [태그 관리]에서 태그를 생성해주세요.".equals(l.getName())),"empty list explains where to create tags");
            check(find(popup,JCheckBox.class).isEmpty(),"empty list does not invent tags");
            check(find(popup,JButton.class).stream().anyMatch(b->"태그 관리".equals(b.getText())),"empty list retains tag management entry");
            render(popup,"empty");
            State state=store.saveTags(List.of(),List.of(new Tag("exam","시험"),new Tag("math","미적분")));
            AtomicReference<State> saved=new AtomicReference<>(state);
            PlannerDialogs.EventEditor editor=new PlannerDialogs.EventEditor(store,state,null,LocalDateTime.of(2026,10,18,10,0),saved::set,clock);editor.title.setText("태그 선택 확인");
            popup=editor.tagPicker();List<JCheckBox> choices=find(popup,JCheckBox.class);
            check(popup==editor.tagPicker(),"unchanged tag lists reuse the existing view");
            check(choices.stream().map(JCheckBox::getText).toList().equals(List.of("시험","미적분")),"picker lists existing tag names");
            render(popup,"existing");choices.get(0).doClick();
            check(editor.draft().tagIds().equals(List.of("exam")),"choosing a tag immediately updates the event draft");
            check(store.load().events().isEmpty(),"choosing a tag does not save the unfinished event");
            choices=find(editor.tagPicker(),JCheckBox.class);check(choices.get(0).isSelected(),"reopened picker reflects selection");choices.get(0).doClick();
            check(editor.selected.isEmpty(),"selected tag can be deselected from the list");
            choices=find(editor.tagPicker(),JCheckBox.class);choices.get(1).doClick();editor.save();
            Event event=saved.get().events().get(0);check(event.tagIds().equals(List.of("math")),"event save persists the selected tag ID");
            PlannerDialogs.EventEditor reopened=new PlannerDialogs.EventEditor(store,store.load(),event,event.start(),s->{},clock);
            check(find(reopened.tagPicker(),JCheckBox.class).get(1).isSelected(),"editing a saved event restores the tag selection");
            testRepeatedOpening(reopened);
            List<Tag> many=new ArrayList<>();for(int i=0;i<40;i++)many.add(new Tag("tag-"+i,"태그 "+i));
            State manyState=store.saveTags(state.tags(),many);
            PlannerDialogs.EventEditor longList=new PlannerDialogs.EventEditor(store,manyState,null,event.start(),s->{},clock);popup=longList.tagPicker();
            check(find(popup,JCheckBox.class).size()==40,"long lists retain every tag");
            JScrollPane list=find(popup,JScrollPane.class).get(0);check(list.getPreferredSize().height<=240,"long list scrolls within a bounded popup");render(popup,"many");
            testModalCleanup();
        }catch(Exception error){throw new RuntimeException(error);}});
        // A subsequent event must still execute after all selection and failure paths.
        SwingUtilities.invokeAndWait(()->check(true,"event dispatch remains responsive"));
        System.out.println("PASS: "+checks+" tag picker, persistence and modal cleanup checks; renders in "+OUTPUT.toAbsolutePath());
    }
    private static void testRepeatedOpening(PlannerDialogs.EventEditor editor){
        JRootPane root=new JRootPane();root.setContentPane(editor);root.setSize(1126,850);layout(root);layout(root);
        JLayeredPane layer=root.getLayeredPane();int count=layer.getComponentCount();
        JPanel reused=editor.tagPicker();int contentListeners=reused.getMouseListeners().length;
        for(int i=0;i<30;i++){
            editor.addTag.doClick();check(editor.tagPopover!=null&&layer.getComponentCount()==count+1,"one list appears on repeated open "+i);
            check(editor.tagPopover.getWidth()<layer.getWidth()&&editor.tagPopover.getHeight()<layer.getHeight(),"list never creates a full-window click cover "+i);
            check(MenuSelectionManager.defaultManager().getSelectedPath().length==0,"tag list never captures the global menu mouse grab "+i);
            editor.addTag.doClick();check(editor.tagPopover==null&&layer.getComponentCount()==count,"repeated button click removes the entire list "+i);
            boolean before=editor.important.isSelected();editor.important.doClick();check(editor.important.isSelected()!=before,"other controls respond after repeated list closing "+i);
        }
        check(reused.getMouseListeners().length==contentListeners,"reusing the list never accumulates mouse listeners");
        int listeners=Toolkit.getDefaultToolkit().getAWTEventListeners(java.awt.AWTEvent.MOUSE_EVENT_MASK).length;
        editor.addTag.doClick();
        java.awt.event.MouseEvent outside=new java.awt.event.MouseEvent(editor.title,java.awt.event.MouseEvent.MOUSE_PRESSED,System.currentTimeMillis(),0,2,2,1,false,java.awt.event.MouseEvent.BUTTON1);
        editor.title.dispatchEvent(outside);
        check(editor.tagPopover==null&&layer.getComponentCount()==count,"outside click closes only the bounded list");
        check(!outside.isConsumed(),"outside click continues to the intended form control");
        check(Toolkit.getDefaultToolkit().getAWTEventListeners(java.awt.AWTEvent.MOUSE_EVENT_MASK).length==listeners,"closing the list removes its outside-click observer");
        editor.addTag.doClick();
        KeyboardFocusManager.getCurrentKeyboardFocusManager().dispatchEvent(new java.awt.event.KeyEvent(editor.addTag,java.awt.event.KeyEvent.KEY_PRESSED,System.currentTimeMillis(),0,java.awt.event.KeyEvent.VK_ESCAPE,(char)27));
        check(editor.tagPopover==null&&layer.getComponentCount()==count,"Escape closes the list without opening editor discard confirmation");
        editor.addTag.doClick();find(editor.tagPopover,JCheckBox.class).get(0).doClick();
        check(editor.tagPopover==null&&layer.getComponentCount()==count,"tag selection cleans up the click-catching layer");
    }
    private static void testModalCleanup(){
        JRootPane root=new JRootPane();Component original=root.getGlassPane();original.setVisible(false);
        RuntimeException failure=new IllegalStateException("simulated dialog setup failure");
        try{PlannerDialogs.withDimmedOwner(root,()->{check(root.getGlassPane()!=original&&root.getGlassPane().isVisible(),"dialog dims its owner while open");throw failure;});throw new AssertionError("setup failure was swallowed");}
        catch(RuntimeException expected){check(expected==failure,"dialog setup failure remains visible to the caller");}
        check(root.getGlassPane()==original&&!original.isVisible(),"failed dialog restores input instead of leaving a blocking overlay");
        original.setVisible(true);
        PlannerDialogs.withDimmedOwner(root,()->{Component outer=root.getGlassPane();PlannerDialogs.withDimmedOwner(root,()->{});check(root.getGlassPane()==outer&&outer.isVisible(),"nested dialog restores its parent overlay");});
        check(root.getGlassPane()==original&&original.isVisible(),"existing visible overlay is preserved");
    }
    private static <T extends Component>List<T> find(Container root,Class<T> type){List<T> result=new ArrayList<>();for(Component c:root.getComponents()){if(type.isInstance(c))result.add(type.cast(c));if(c instanceof Container child)result.addAll(find(child,type));}return result;}
    private static void layout(Container c){c.doLayout();for(Component child:c.getComponents())if(child instanceof Container nested)layout(nested);}
    private static void render(JPanel popup,String name)throws Exception{popup.setSize(popup.getPreferredSize());layout(popup);BufferedImage image=new BufferedImage(popup.getWidth(),popup.getHeight(),BufferedImage.TYPE_INT_ARGB);Graphics2D g=image.createGraphics();popup.printAll(g);g.dispose();ImageIO.write(image,"png",OUTPUT.resolve(name+".png").toFile());}
}
