function csrfSafeMethod(e){return/^(GET|HEAD|OPTIONS|TRACE)$/.test(e)}function formlessAjaxPostCSRFSetup(){var e=$.cookie("csrftoken");$.ajaxSetup({beforeSend:function(t,o){csrfSafeMethod(o.type)||this.crossDomain||t.setRequestHeader("X-CSRFToken",e)}})}