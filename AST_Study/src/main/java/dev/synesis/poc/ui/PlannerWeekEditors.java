package dev.synesis.poc.ui;

import dev.synesis.poc.planner.PlannerModel;
import javax.swing.*;
import java.awt.*;
import java.time.*;
import java.time.format.DateTimeFormatter;
import java.util.*;
import java.util.List;
import static dev.synesis.poc.planner.PlannerModel.*;
import static dev.synesis.poc.ui.PlannerStyle.*;
import static dev.synesis.poc.ui.PlannerDialogs.*;

/** Editors for daily TODOs, weekly TODOs and counted goals. Events keep their existing editor. */
final class PlannerWeekEditors {
    private PlannerWeekEditors() {}
    static String weekLabel(LocalDate value){LocalDate start=weekStart(value);return start.format(DateTimeFormatter.ofPattern("uuuu.MM.dd"))+" — "+start.plusDays(6).format(DateTimeFormatter.ofPattern("MM.dd"));}
    static DateInput weekInput(String name,LocalDate value){
        DateInput input=new DateInput(name,value).weeks();Runnable update=()->input.setText(weekLabel(input.date()));input.onChange(update);update.run();return input;
    }
    abstract static class Form extends ModalPanel {
        final PlannerDesign planner;
        final JPanel fields=new JPanel();
        final JLabel error=label("",12,ERROR_COLOR);
        final JPanel footer=new JPanel(new BorderLayout(8,12)),buttons=new JPanel(new FlowLayout(FlowLayout.RIGHT,8,0));
        final JButton saveButton;
        Form(PlannerDesign planner,String title){
            super(new BorderLayout());this.planner=planner;setBackground(Color.WHITE);name(this,title);
            putClientProperty("planner.backdropDismiss",true);
            add(header(title,"",()->requestClose(this)),BorderLayout.NORTH);
            fields.setLayout(new BoxLayout(fields,BoxLayout.Y_AXIS));fields.setBackground(Color.WHITE);fields.setBorder(BorderFactory.createEmptyBorder(16,24,12,24));add(PlannerWeekView.quietScroll(fields));
            footer.setOpaque(false);footer.setBorder(BorderFactory.createEmptyBorder(12,24,20,24));buttons.setOpaque(false);
            buttons.add(button("취소",false,()->requestClose(this)));saveButton=button("저장",true,this::save);buttons.add(saveButton);
            for(Component c:buttons.getComponents())c.setPreferredSize(new Dimension(80,36));
            footer.add(error,BorderLayout.NORTH);footer.add(buttons,BorderLayout.EAST);add(footer,BorderLayout.SOUTH);putClientProperty("planner.defaultButton",saveButton);
        }
        void fieldRow(String caption,JComponent field,int height){
            JLabel label=label(caption,12,INK);label.setAlignmentX(LEFT_ALIGNMENT);field.setAlignmentX(LEFT_ALIGNMENT);
            fields.add(label);fields.add(Box.createVerticalStrut(6));field.setMaximumSize(new Dimension(Integer.MAX_VALUE,height));field.setPreferredSize(new Dimension(400,height));fields.add(field);fields.add(Box.createVerticalStrut(16));
        }
        void delete(Runnable action){JButton remove=button("삭제",false,()->confirmDelete(this,"이 항목을 삭제할까요?",action));remove.setForeground(ERROR_COLOR);remove.setPreferredSize(new Dimension(64,36));footer.add(remove,BorderLayout.WEST);}
        void commit(PlannerDesign.Save write){try{planner.accept(write.run());close(this);}catch(Exception e){error.setText(e.getMessage());error.setToolTipText(e.getMessage());}}
        abstract void save();
    }
    static final class Daily extends Form {
        final Task original;final JTextField title;final JTextArea detail;final DateInput date;
        Daily(PlannerDesign planner,Task original){
            super(planner,original==null?"오늘의 TODO 생성":"오늘의 TODO 편집");this.original=original;
            title=field("TODO 제목",original==null?"":original.title());detail=new JTextArea(original==null?"":original.detail());
            detail.setFont(regular(14));detail.setForeground(INK);detail.setLineWrap(true);detail.setWrapStyleWord(true);detail.setBorder(BorderFactory.createEmptyBorder(8,0,8,0));name(detail,"TODO 설명");
            date=new DateInput("TODO 날짜 선택",original==null?planner.taskDate:original.date());
            fieldRow("TODO 제목 *",title,40);JScrollPane text=scroll(detail);text.setBorder(inputBorder());fieldRow("TODO 설명",text,72);fieldRow("TODO 날짜 선택",date,40);
            if(original!=null)delete(()->commit(()->planner.store.deleteTask(original.id())));
        }
        @Override void save(){try{Task value=new Task(original==null?PlannerModel.id():original.id(),title.getText(),date.date(),detail.getText(),original!=null&&original.completed());commit(()->planner.store.saveTask(value));}catch(Exception e){error.setText(e.getMessage());}}
    }
    static final class Todo extends Form {
        final WeeklyTask original;final MonthlyTask monthlyOriginal;final boolean monthly;final JTextField title;final DateInput deadline,week;
        final JCheckBox noDeadline=check("마감일 없음 - 이번 주 까지");
        final JPanel chips=new JPanel(new PlannerWeekView.WrapLayout());final Set<String> selected=new LinkedHashSet<>();
        State state;PlannerPopover popover;final JButton addTag;
        Todo(PlannerDesign planner,WeeklyTask original){
            this(planner,original,null,false);
        }
        static Todo monthly(PlannerDesign planner,MonthlyTask original){return new Todo(planner,null,original,true);}
        private Todo(PlannerDesign planner,WeeklyTask original,MonthlyTask monthlyOriginal,boolean monthly){
            super(planner,(monthly?"이번 달":"이번 주")+(original==null&&monthlyOriginal==null?" TODO 생성":" TODO 편집"));this.original=original;this.monthlyOriginal=monthlyOriginal;this.monthly=monthly;state=planner.state;
            title=field("TODO 제목",monthly?(monthlyOriginal==null?"":monthlyOriginal.title()):(original==null?"":original.title()));
            week=monthly?new DateInput("TODO의 월",monthlyOriginal==null?planner.anchor:monthlyOriginal.month()).months():weekInput("TODO의 주",original==null?planner.anchor:original.week());
            LocalDate end=periodEnd(),savedDate=monthly?(monthlyOriginal==null?end:monthlyOriginal.deadline()):(original==null?end:original.deadline());
            deadline=monthly?new DateInput("마감일",clampDeadline(savedDate==null?end:savedDate)).withinMonth(()->week.date()):new DateInput("마감일",clampDeadline(savedDate==null?end:savedDate),()->week.date());
            noDeadline.setText(monthly?"마감일 없음 - 이번 달 까지":"마감일 없음 - 이번 주 까지");
            noDeadline.setSelected((original!=null||monthlyOriginal!=null)&&savedDate==null);noDeadline.addActionListener(e->syncDeadline());syncDeadline();
            week.onChange(()->{if(!monthly)week.setText(weekLabel(week.date()));deadline.setDate(clampDeadline(deadline.date()));});
            if(original!=null)selected.addAll(original.tagIds());if(monthlyOriginal!=null)selected.addAll(monthlyOriginal.tagIds());
            JPanel deadlineChoice=new JPanel(new BorderLayout(0,6));deadlineChoice.setOpaque(false);deadlineChoice.add(deadline);deadlineChoice.add(noDeadline,BorderLayout.SOUTH);
            fieldRow("TODO 제목 *",title,40);fieldRow("마감일",deadlineChoice,72);fieldRow(monthly?"TODO의 월":"TODO의 주",week,40);
            JPanel tags=new JPanel(new BorderLayout(8,4));tags.setOpaque(false);chips.setOpaque(false);addTag=button("+ 태그 추가",false,this::toggleTags);
            JPanel actions=new JPanel(new FlowLayout(FlowLayout.LEFT,6,0));actions.setOpaque(false);addTag.setPreferredSize(new Dimension(108,30));actions.add(addTag);JButton manage=button("태그 관리",false,this::manageTags);manage.setPreferredSize(new Dimension(88,30));actions.add(manage);tags.add(actions,BorderLayout.NORTH);
            JScrollPane chipScroll=scroll(chips);tags.add(chipScroll);fieldRow("태그 · 여러 개 선택할 수 있어요",tags,88);renderTags();
            if(monthlyOriginal!=null)delete(()->commit(()->planner.store.deleteMonthlyTask(monthlyOriginal.id())));else if(original!=null)delete(()->commit(()->planner.store.deleteWeeklyTask(original.id())));
        }
        LocalDate periodEnd(){return monthly?YearMonth.from(week.date()).atEndOfMonth():weekStart(week.date()).plusDays(6);}
        LocalDate clampDeadline(LocalDate date){LocalDate start=monthly?week.date().withDayOfMonth(1):weekStart(week.date()),end=periodEnd();return date.isBefore(start)?start:date.isAfter(end)?end:date;}
        void syncDeadline(){deadline.setEnabled(!noDeadline.isSelected());}
        void hideTags(){if(popover!=null)popover.close();}
        void renderTags(){
            hideTags();selected.removeIf(id->state.todoTags().stream().noneMatch(t->t.id().equals(id)));chips.removeAll();
            for(Tag tag:state.todoTags())if(selected.contains(tag.id())){JButton chip=button(tag.name()+" ×",false,()->{selected.remove(tag.id());renderTags();});chip.setBackground(SURFACE);chip.setPreferredSize(new Dimension(Math.min(180,chip.getPreferredSize().width),26));chips.add(chip);}
            chips.revalidate();chips.repaint();
        }
        void toggleTags(){if(popover!=null){hideTags();return;}popover=new PlannerPopover(addTag,tagPicker(),()->popover=null);try{popover.showList();}catch(RuntimeException e){hideTags();throw e;}}
        JPanel tagPicker(){
            JPanel p=new JPanel(new BorderLayout(0,8));p.setBackground(Color.WHITE);p.setBorder(BorderFactory.createCompoundBorder(BorderFactory.createLineBorder(BORDER),BorderFactory.createEmptyBorder(12,12,12,12)));name(p,"TODO 태그 선택");
            JPanel rows=new JPanel();rows.setBackground(Color.WHITE);rows.setLayout(new BoxLayout(rows,BoxLayout.Y_AXIS));
            if(state.todoTags().isEmpty()){JLabel empty=label("<html>태그가 없어요.<br>[태그 관리]에서 태그를 생성해주세요.</html>",12,MUTED);empty.setPreferredSize(new Dimension(296,48));rows.add(empty);}
            for(Tag tag:state.todoTags()){JCheckBox choice=check(tag.name());choice.setSelected(selected.contains(tag.id()));choice.setMaximumSize(new Dimension(Integer.MAX_VALUE,32));choice.setPreferredSize(new Dimension(296,32));choice.addActionListener(e->{if(choice.isSelected())selected.add(tag.id());else selected.remove(tag.id());renderTags();});rows.add(choice);}
            JScrollPane list=scroll(rows);list.setPreferredSize(new Dimension(296,Math.max(48,Math.min(240,state.todoTags().size()*32))));p.add(list);p.add(button("태그 관리",false,()->{hideTags();SwingUtilities.invokeLater(this::manageTags);}),BorderLayout.SOUTH);return p;
        }
        void manageTags(){hideTags();TagEditor editor=new TagEditor(planner.store,state,selected,(next,ids)->{state=next;selected.clear();selected.addAll(ids);planner.accept(next);renderTags();},true);showDialog(this,editor,"TODO 태그 관리",440,536);}
        @Override public void removeNotify(){hideTags();super.removeNotify();}
        @Override void save(){if(monthly){try{MonthlyTask value=new MonthlyTask(monthlyOriginal==null?PlannerModel.id():monthlyOriginal.id(),title.getText(),noDeadline.isSelected()?null:deadline.date(),week.date(),new ArrayList<>(selected),monthlyOriginal!=null&&monthlyOriginal.completed());commit(()->planner.store.saveMonthlyTask(value));}catch(Exception e){error.setText(e.getMessage());}return;}try{WeeklyTask value=new WeeklyTask(original==null?PlannerModel.id():original.id(),title.getText(),noDeadline.isSelected()?null:deadline.date(),week.date(),new ArrayList<>(selected),original!=null&&original.completed());commit(()->planner.store.saveWeeklyTask(value));}catch(Exception e){error.setText(e.getMessage());}}
    }
    static final class GoalEditor extends Form {
        final WeeklyGoal original;final JTextField title;final JSpinner target;final DateInput week;
        GoalEditor(PlannerDesign planner,WeeklyGoal original){
            super(planner,original==null?"이번 주 목표 생성":"이번 주 목표 편집");this.original=original;
            title=field("목표 제목",original==null?"":original.title());target=new JSpinner(new SpinnerNumberModel(original==null?3:original.target(),1,100000,1));name(target,"목표 횟수");target.setFont(regular(14));
            week=weekInput("목표의 주",original==null?planner.anchor:original.week());fieldRow("목표 제목 *",title,40);fieldRow("횟수 *",target,40);fieldRow("어느 주의 목표인가요?",week,40);
            if(original!=null)delete(()->commit(()->planner.store.deleteWeeklyGoal(original.id())));
        }
        @Override void save(){try{target.commitEdit();int count=(Integer)target.getValue();WeeklyGoal value=new WeeklyGoal(original==null?PlannerModel.id():original.id(),title.getText(),week.date(),count,original==null?0:Math.min(original.completed(),count));commit(()->planner.store.saveWeeklyGoal(value));}catch(Exception e){error.setText(e.getMessage());}}
    }
}
