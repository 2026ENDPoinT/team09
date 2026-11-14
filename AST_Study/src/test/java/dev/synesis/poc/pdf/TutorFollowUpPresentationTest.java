package dev.synesis.poc.pdf;

import com.google.gson.*;

/** Offline display guards also protect old saved answers from invalid suggestions. */
public final class TutorFollowUpPresentationTest {
    public static void main(String[] args) {
        JsonObject result=new JsonObject();
        result.addProperty("answer","확인한 답변은 그대로 보여요.");
        result.addProperty("kind","ai_generated");
        for(String offer:new String[]{"운동량을 설명해줄까?","운동량을 설명해 줄까요?",
                "계산 방법을 알려드릴까요?","예시를 보여 줄까?","운동량을 계산해볼까요?","같이 살펴볼까요?"}) {
            result.addProperty("followUpQuestion",offer);
            require(TutorPresentation.followUp(result).isEmpty(),"tutor offer became a user message: "+offer);
        }
        for(String question:new String[]{"충격량과 운동량의 관계에 대해 설명해줘.",
                "속도가 두 배가 되면 운동에너지는 왜 네 배야?",
                "영업이익은 흑자인데 당기순이익은 적자일 수도 있어?","이 식을 숫자 예시로 풀어줄 수 있어?"}) {
            result.addProperty("followUpQuestion",question);
            require(TutorPresentation.followUp(result).equals(question),"student request changed: "+question);
        }
        result.addProperty("followUpQuestion","  운동에너지와 운동량은 어떻게 달라?  ");
        String originalAnswer=result.get("answer").getAsString();
        require(TutorPresentation.followUp(result).equals("운동에너지와 운동량은 어떻게 달라?"),"valid question lost");
        for(String flag:new String[]{"blocked","notFound","needsClarification","evidenceIncomplete","needsExternalSearch"}) {
            result.addProperty(flag,true);
            require(TutorPresentation.followUp(result).isEmpty(),"unresolved result exposed a suggestion: "+flag);
            result.addProperty(flag,false);
        }
        for(String kind:new String[]{"blocked","greeting","social","error","no_evidence"}) {
            result.addProperty("kind",kind);
            require(TutorPresentation.followUp(result).isEmpty(),"non-answer exposed a suggestion: "+kind);
        }
        result.addProperty("kind","ai_generated");
        for(String value:new String[]{"한 질문\n다른 질문","한 질문\u2028다른 질문","한 질문\u2029다른 질문",
                                      "```질문```","x".repeat(161)}) {
            result.addProperty("followUpQuestion",value);
            require(TutorPresentation.followUp(result).isEmpty(),"invalid single-line metadata accepted");
        }
        result.addProperty("followUpQuestion","😀".repeat(80));
        require(TutorPresentation.followUp(result).codePointCount(0,TutorPresentation.followUp(result).length())==80,
            "Java and Python disagree on Unicode length");
        result.add("followUpQuestion",new JsonObject());
        require(TutorPresentation.followUp(result).isEmpty(),"nested metadata accepted");
        result.remove("followUpQuestion");
        require(TutorPresentation.followUp(result).isEmpty(),"legacy answer requires metadata");
        require(result.get("answer").getAsString().equals(originalAnswer),"display changed the answer");
        System.out.println("TutorFollowUpPresentationTest: valid, unresolved, legacy and Unicode metadata passed; answer untouched");
    }
    private static void require(boolean value,String message) {
        if(!value)throw new AssertionError(message);
    }
}
